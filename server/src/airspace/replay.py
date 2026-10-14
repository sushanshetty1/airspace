"""Replays: a real run, recorded so Tower can play it back without agents.

A replay is one JSON document:

    {"version": 1, "recorded_at": float, "events": [...], "frames": [...],
     "collisions": {id: collision()}, "insights": insights()}

Each frame is {"at": event time, "state": state(), "radar": radar()} as they were at that moment. The read models
describe the graph as it is now, so true frames can only be taken while the run happens: `Recorder.snapshot()`
appends one whenever new events have arrived, and `watch` polls it every half second during a run. `record()` works
after the fact from the final graph and so keeps every event but only one frame, the final one.

    python -m airspace.replay watch --root DIR --out FILE [--seconds N]
    python -m airspace.replay summarize FILE
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

VERSION = 1
EVENT_LIMIT = 10000
# Events can share a timestamp, so each poll looks back a little and drops ids it has seen.
_OVERLAP = 1.0


class Recorder:
    """Builds a replay from an Airspace-like engine while a run happens."""

    def __init__(self, airspace: Any):
        self.airspace = airspace
        self.events: list[dict] = []
        self.frames: list[dict] = []
        self._seen: set[str] = set()
        self._last_at = 0.0

    def snapshot(self) -> bool:
        """Append the current state and radar if events arrived since the last snapshot. True when a frame was added."""
        since = max(0.0, self._last_at - _OVERLAP) if self._seen else 0.0
        fresh = [e for e in self.airspace.events(since, limit=EVENT_LIMIT) if e["id"] not in self._seen]
        if not fresh:
            return False
        for e in fresh:
            self._seen.add(e["id"])
            self._last_at = max(self._last_at, float(e["at"]))
        self.events.extend(fresh)
        self.events.sort(key=lambda e: e["at"])
        self.frames.append({"at": self._last_at, "state": self.airspace.state(), "radar": self.airspace.radar()})
        return True

    def document(self) -> dict:
        return _document(self.airspace, self.events, self.frames)

    def save(self, out: Path) -> dict:
        doc = self.document()
        _write(out, doc)
        return doc


def _document(airspace: Any, events: list[dict], frames: list[dict]) -> dict:
    ids: list[str] = []
    for frame in frames:
        for c in frame["state"].get("collisions") or []:
            if c["id"] not in ids:
                ids.append(c["id"])
    collisions = {cid: detail for cid in ids if (detail := airspace.collision(cid)) is not None}
    return {
        "version": VERSION,
        "recorded_at": time.time(),
        "events": events,
        "frames": frames,
        "collisions": collisions,
        "insights": airspace.insights(),
    }


def _write(out: Path, doc: dict) -> None:
    """Atomic, so a reader (or a crash mid-run) never sees half a file."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n")
    os.replace(tmp, out)


def record(graph, out: Path) -> dict:
    """A replay of the run already in `graph`: every event, its collisions and one frame, the final state."""
    from airspace.admission.engine import Airspace
    from airspace.config import settings

    s = settings()
    airspace = Airspace(graph, lease_seconds=s.lease_seconds, cone_depth=s.cone_depth)
    events = airspace.events(0, limit=EVENT_LIMIT)
    frames = [{"at": events[-1]["at"], "state": airspace.state(), "radar": airspace.radar()}] if events else []
    doc = _document(airspace, events, frames)
    _write(out, doc)
    return doc


def load(path: Path) -> dict:
    """Read a replay file. Raises ValueError when it is not one."""
    doc = json.loads(Path(path).read_text())
    if not isinstance(doc, dict) or doc.get("version") != VERSION or not isinstance(doc.get("frames"), list):
        raise ValueError(f"{path} is not an Airspace replay (version {VERSION})")
    return doc


# The command line.


def _open(root: Path):
    from airspace.api.app import open_airspace

    return open_airspace(root)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _cmd_watch(root: Path, out: Path, seconds: float | None, interval: float) -> int:
    try:
        airspace = _open(root)
    except Exception as e:
        detail = " ".join(str(e).split()) or type(e).__name__
        print(f"airspace: FalkorDB unavailable ({detail})", file=sys.stderr)
        return 1
    rec = Recorder(airspace)
    started = time.monotonic()
    limit = f"for {seconds:g} s" if seconds is not None else "until Ctrl-C"
    print(f"Recording {root} into {out} {limit}", file=sys.stderr)
    try:
        while True:
            if rec.snapshot():
                rec.save(out)
                print(f"  frame {len(rec.frames)}: {_plural(len(rec.events), 'event')}", file=sys.stderr)
            left = None if seconds is None else seconds - (time.monotonic() - started)
            if left is not None and left <= 0:
                break
            time.sleep(interval if left is None else min(interval, left))
    except KeyboardInterrupt:
        pass
    rec.save(out)
    print(f"Wrote {out}: {_plural(len(rec.events), 'event')}, {_plural(len(rec.frames), 'frame')}", file=sys.stderr)
    return 0


def summarize(doc: dict) -> str:
    events = doc.get("events") or []
    frames = doc.get("frames") or []
    agents = sorted({e["agent"] for e in events if e.get("agent")})
    lines = [
        f"Airspace replay, version {doc.get('version')}, recorded "
        + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(doc.get("recorded_at") or 0)),
        (
            f"  {_plural(len(events), 'event')}, {_plural(len(frames), 'frame')}, "
            f"{_plural(len(doc.get('collisions') or {}), 'collision')}"
        ),
    ]
    if events:
        lines.append(f"  {events[-1]['at'] - events[0]['at']:.1f} s from the first event to the last")
    lines.append(f"  agents: {', '.join(agents) or 'none'}")
    kinds = Counter(e.get("kind") for e in events)
    if kinds:
        lines.append("  " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m airspace.replay", description="Record and inspect Tower replays.")
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="record a run as it happens, a frame for every new event")
    watch.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    watch.add_argument("--out", type=Path, required=True, help="replay file to write")
    watch.add_argument("--seconds", type=float, default=None, help="stop after this long (default: until Ctrl-C)")
    watch.add_argument("--interval", type=float, default=0.5, help="seconds between polls (default: 0.5)")
    show = sub.add_parser("summarize", help="print what a replay file holds")
    show.add_argument("file", type=Path)

    args = parser.parse_args(argv)
    if args.command == "watch":
        return _cmd_watch(args.root.resolve(), args.out, args.seconds, args.interval)
    try:
        doc = load(args.file)
    except (OSError, ValueError) as e:
        print(f"airspace: {e}", file=sys.stderr)
        return 1
    print(summarize(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
