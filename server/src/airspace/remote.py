"""The client half of a hosted workspace: the hooks, `airspace index` and `airspace status` talk to a server.

A repository connected with `airspace connect` has an entry in ~/.config/airspace/remotes.json. Its hooks then send
engine calls and parsed facts over RPC instead of opening FalkorDB. Parsing and diffing stay on this machine: the
server receives symbol names, signatures, call shapes and the one-line text of calls, never a whole file. The last
version of each file the hooks saw, which reconcile diffs shell writes against, is kept under ~/.cache/airspace.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from airspace.types import Briefing, CallSite, SignatureChange, Verdict
from airspace.wire import decode, encode

# A hook runs on every edit: a server that stalls must not stall the agent for long.
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 15.0
# graph.index sends parsed files in batches, under the server's 2 MB body limit with room to spare.
BATCH_FILES = 200
BATCH_BYTES = 1_500_000


class RemoteError(Exception):
    """The server could not be reached, refused the key, or answered with an error. `status` is the HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# Configuration


@dataclass(frozen=True)
class Remote:
    server: str  # "https://airspace.sushans.dev", no trailing slash
    key: str  # "ask_..."
    workspace: str  # 12 hex characters


def config_dir() -> Path:
    return Path(os.environ.get("AIRSPACE_CONFIG_DIR") or Path.home() / ".config" / "airspace")


def cache_dir() -> Path:
    return Path(os.environ.get("AIRSPACE_CACHE_DIR") or Path.home() / ".cache" / "airspace")


def seen_dir() -> Path:
    return cache_dir() / "seen"


def remotes_path() -> Path:
    return config_dir() / "remotes.json"


def _repo_key(root: Path | str) -> str:
    # The same repository reached through a symlink or a relative path is one entry.
    return os.path.realpath(root)


def load_remotes() -> dict[str, dict]:
    path = remotes_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise RemoteError(f"cannot read {path} ({e})") from e
    try:
        data = json.loads(text or "{}")
    except ValueError as e:
        raise RemoteError(f"{path} is not valid JSON ({e})") from e
    if not isinstance(data, dict):
        raise RemoteError(f"{path} is not a JSON object")
    return data


def save_remotes(remotes: dict[str, dict]) -> None:
    """Write the file readable by its owner only: it holds keys. Replaced in one step, so a reader never sees half."""
    path = remotes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(remotes, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def remote_for(root: Path | str) -> Remote | None:
    entry = load_remotes().get(_repo_key(root))
    if not isinstance(entry, dict):
        return None
    try:
        return Remote(server=str(entry["server"]).rstrip("/"), key=str(entry["key"]), workspace=str(entry["workspace"]))
    except KeyError as e:
        raise RemoteError(f"{remotes_path()} entry for {_repo_key(root)} has no {e.args[0]}") from e


def set_remote(root: Path | str, remote: Remote) -> None:
    remotes = load_remotes()
    remotes[_repo_key(root)] = asdict(remote)
    save_remotes(remotes)


def remove_remote(root: Path | str) -> bool:
    """Forget the repository's server. False when it had none."""
    remotes = load_remotes()
    if remotes.pop(_repo_key(root), None) is None:
        return False
    save_remotes(remotes)
    return True


# RPC


class RpcClient:
    """POST {server}/api/rpc with the workspace key. Values travel in airspace.wire form."""

    def __init__(self, server: str, key: str, transport: Any = None):
        import httpx

        self.server = server.rstrip("/")
        # The X-Airspace-Workspace header of the last answer: the workspace the key belongs to.
        self.workspace: str | None = None
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
            transport=transport,
        )

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        import httpx

        body = {"method": method, "args": encode(list(args)), "kwargs": encode(kwargs)}
        try:
            response = self._http.post(f"{self.server}/api/rpc", json=body)
        except httpx.HTTPError as e:
            raise RemoteError(f"{self.server} did not answer: {type(e).__name__}") from e
        self.workspace = response.headers.get("X-Airspace-Workspace")
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            error = data.get("error") if isinstance(data, dict) else None
            raise RemoteError(str(error or f"HTTP {response.status_code} from {self.server}"), response.status_code)
        return decode(data.get("result"))

    def close(self) -> None:
        self._http.close()


def client_for(remote: Remote) -> RpcClient:
    return RpcClient(remote.server, remote.key)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class RemoteAirspace:
    """The engine's interface for the hooks, reconcile, `airspace status` and the MCP server, run on the server.

    Every method forwards to the workspace's engine except seen_source and note_seen: the last version of a file the
    hooks saw stays on this machine, so whole files never leave it.
    """

    def __init__(self, client: RpcClient, seen_dir: Path):
        self.client = client
        self.seen_dir = Path(seen_dir)

    def _call(self, method: str, *args: Any) -> Any:
        return self.client.call(method, *args)

    # Tasks and leases

    def ensure_task(self, agent_id: str, task_id: str, intent: str = "") -> None:
        self._call("ensure_task", agent_id, task_id, intent)

    def agent_of(self, task_id: str) -> str | None:
        return self._call("agent_of", task_id)

    def claim(self, task_id: str, qualnames: list[str]) -> list[str]:
        return self._call("claim", task_id, qualnames)

    def claim_pending(self, task_id: str) -> list[str]:
        return self._call("claim_pending", task_id)

    def file_plan(self, agent_id: str, task_id: str, intent: str, qualnames: list[str]) -> list[str]:
        return self._call("file_plan", agent_id, task_id, intent, qualnames)

    def release(self, task_id: str) -> None:
        self._call("release", task_id)

    # Clearance and contracts

    def check_edit(
        self,
        task_id: str,
        touched: list[str],
        new_calls: list[tuple[str, str]],
        call_shapes: dict[str, list[CallSite]] | None = None,
    ) -> Verdict:
        return self._call("check_edit", task_id, touched, new_calls, call_shapes)

    def record_changes(self, task_id: str, changes: list[SignatureChange]) -> list[str]:
        return self._call("record_changes", task_id, changes)

    def renamed(self, qualnames: list[str]) -> dict[str, tuple[str, str]]:
        return {old: tuple(new) for old, new in (self._call("renamed", qualnames) or {}).items()}

    def pending_briefings(self, task_id: str) -> list[Briefing]:
        return self._call("pending_briefings", task_id)

    def pending_messages(self, agent_id: str, task_id: str | None = None) -> list[str]:
        return self._call("pending_messages", agent_id, task_id)

    # What the task did

    def record_edited_file(self, task_id: str, rel: str) -> None:
        self._call("record_edited_file", task_id, rel)

    def edited_files(self, task_id: str) -> list[str]:
        return self._call("edited_files", task_id)

    def note_touched(self, task_id: str, qualnames: list[str]) -> None:
        self._call("note_touched", task_id, qualnames)

    def owned(self, task_id: str, qualnames: list[str]) -> list[str]:
        return self._call("owned", task_id, qualnames)

    def restore_signatures(self, signatures: list[tuple[str, str]]) -> None:
        self._call("restore_signatures", signatures)

    def started_at(self, task_id: str) -> float | None:
        return self._call("started_at", task_id)

    def note_reading(self, agent_id: str, task_id: str, rel: str) -> None:
        self._call("note_reading", agent_id, task_id, rel)

    def note_interest_from_text(self, agent_id: str, task_id: str, text: str) -> list[str]:
        return self._call("note_interest_from_text", agent_id, task_id, text)

    # Landing

    def stop_check(self, task_id: str, calls: list[tuple[str, str, CallSite]]) -> tuple[list[dict], list[str]]:
        violations, waiting_on = self._call("stop_check", task_id, calls)
        return violations, waiting_on

    def holding(self, task_id: str, on_agent: str) -> None:
        self._call("holding", task_id, on_agent)

    def land(self, task_id: str) -> None:
        self._call("land", task_id)

    def block_landing(self, task_id: str, fingerprint: str, caller: str) -> None:
        self._call("block_landing", task_id, fingerprint, caller)

    def last_block(self, task_id: str) -> str | None:
        return self._call("last_block", task_id)

    # Read models

    def state(self) -> dict:
        return self._call("state")

    def explain(self, from_q: str, to_q: str) -> list[str]:
        return self._call("explain", from_q, to_q)

    def insights(self) -> dict:
        return self._call("insights")

    def preflight(self, tasks: list[dict], depth: int = 2) -> dict:
        """Pre-flight on the workspace graph. Raises PreflightError, with the server's suggestions, as locally."""
        return remote_preflight(self.client, tasks, depth)

    # Seen sources, local only

    def _seen_path(self, scope: str, rel: str) -> Path:
        return self.seen_dir / _sha1(scope) / _sha1(rel)

    def seen_source(self, scope: str, rel: str) -> str | None:
        """The last version of a file Airspace saw in one working copy, or None if it has seen none there."""
        try:
            with open(self._seen_path(scope, rel), encoding="utf-8", newline="") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def note_seen(self, scope: str, rel: str, source: str) -> None:
        path = self._seen_path(scope, rel)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(source)
        os.replace(tmp, path)


# The code graph, parsed here and written there


def remote_preflight(client: RpcClient, tasks: list[dict], depth: int = 2) -> dict:
    """preflight over RPC (graph.preflight). The server answers bad input as {"error", "suggestions"}."""
    from airspace.admission.preflight import PreflightError

    answer = client.call("graph.preflight", tasks, depth)
    if isinstance(answer, dict) and "error" in answer:
        raise PreflightError(str(answer["error"]), list(answer.get("suggestions") or []))
    return answer


def remote_known(client: RpcClient) -> set[str]:
    """Every qualname in the workspace graph, renamed and removed ones included, as known() is locally, with the
    re-exports its packages declare."""
    from airspace.indexer.resolve import Known

    return Known.decoded(client.call("graph.known") or [])


def _parse(root: Path, rel: str):
    from airspace.indexer.parse import parse_module
    from airspace.indexer.writer import _read

    source = _read(Path(root) / rel)
    return parse_module(rel, source) if source is not None else None


def remote_reindex(client: RpcClient, root: Path, rel: str) -> list[SignatureChange]:
    """reindex_file over RPC: the file is parsed here and its facts are sent. A deleted file sends None.

    A file that does not parse (half-written code) sends nothing, which keeps the last good picture of it.
    """
    rel = Path(rel).as_posix()
    if not (Path(root) / rel).exists():
        return client.call("graph.write_file", rel, None) or []
    facts = _parse(root, rel)
    if facts is None:
        return []
    return client.call("graph.write_file", rel, facts) or []


def _batches(parsed: list) -> list[list]:
    batches: list[list] = [[]]
    size = 0
    for facts in parsed:
        n = len(json.dumps(encode(facts)))
        if batches[-1] and (len(batches[-1]) >= BATCH_FILES or size + n > BATCH_BYTES):
            batches.append([])
            size = 0
        batches[-1].append(facts)
        size += n
    return batches


def remote_index(client: RpcClient, root: Path, reset: bool = True):
    """index_repo over RPC: every Python file index_repo would read is parsed here and sent in batches.

    index_repo writes every symbol before any edge, so a call into a file later in the walk still resolves. Batches
    keep that order when there is more than one: a first round sends each file's symbols without its calls, then a
    second round sends the full facts, when every symbol is already in the graph.
    """
    from dataclasses import replace

    from airspace.indexer.writer import IndexStats, _python_files

    root = Path(root)
    parsed = [f for f in (_parse(root, rel) for rel in _python_files(root)) if f is not None]
    batches = _batches(parsed)
    if len(batches) > 1:
        for i, batch in enumerate(batches):
            skeleton = [replace(f, calls=[], bases=[]) for f in batch]
            client.call("graph.index", skeleton, reset and i == 0)
        reset = False
    totals = {"files": 0, "symbols": 0, "calls": 0, "unresolved": 0}
    for i, batch in enumerate(batches):
        stats = client.call("graph.index", batch, reset and i == 0) or {}
        for k in totals:
            totals[k] += int(stats.get(k, 0))
    return IndexStats(**totals)
