# Airspace demo video

The hackathon demo, composed with [Remotion](https://www.remotion.dev) from headless recordings of the site and an
ElevenLabs voiceover. Output: `out/airspace-demo.mp4`, 1920x1080, 30 fps, H.264 with AAC audio, about 2:48.

```sh
cd video
npm install
npm run voice     # narration and timing (cached; only changed scenes are generated again)
npm run render    # out/airspace-demo.mp4
```

## What is on screen, and where it comes from

| Scene | Source |
| --- | --- |
| The problem | Drawn from a real benchmark run, `server/bench/results/final/slugify-keyword-only--worktrees--r1.json`: both diffs, both agents' passing tests, the merged `TypeError`. 0 of 18 from the README. |
| The idea | The site's hero (`hero` take), then the graph drawn from the replay's own radar data (`server/demo/replay.json`) and the blog fixture's real calls. The Cypher is the README's, as the engine runs it. |
| Tower | The live site's replay of a real run (`tower` take). The replay has no terminals, so the two Claude Code sessions are drawn beside it from the same run's record: the prompts in `docs/demo-script.md`, the edits, and the hold text the edit tool returned (README). |
| Pre-flight | `/preflight` on the live site, Flask (`preflight` take). |
| Memory | A local run (below): the fix written to memory, the sidebar's memory list, and agent-c told the fix. agent-c's terminal shows the hook's own output, `src/data/hooks.json`. |
| Playground | `/playground` on the live site (`playground` take): the story's call held, then the new keyword cleared. |
| Workspaces | The local run: a new workspace, its key (blurred), the real `airspace connect` output, then its live Tower while two sessions are held, messaged and cleared. |
| Results | `src/data/benchmark-flask.json` (a copy of `web/src/data/benchmark-flask.json`) and the README's sample-repo numbers. |

The local run sends the benchmark's reference edits for `slugify-keyword-only` (`server/tests/bench_refs.py`) through
Airspace's real Claude Code hooks (`capture/session.py`), into a workspace on a local copy of the hosted app. No model
runs there; the engine and the hooks are the real ones. GitHub sign-in needs a real OAuth app, so the local stack
signs in with the same signed session cookie a GitHub sign-in sets (`capture/signin.py`).

## How it is made

| Path | What it is |
| --- | --- |
| `capture/takes.mjs` | Every recorded scene, scripted: clicks, typing with a person's rhythm, smooth scrolls |
| `capture/lib.mjs` | Headless Chrome with a CDP screencast of 2x frames (3200x1800 for a 1600x900 viewport), and the log of every interaction |
| `capture/stack.mjs` | The local stack for the signed-in takes: `airspace serve` on 8810 and Vite on 4210 |
| `capture/session.py` | One step of the local run, through the real hooks |
| `narration/script.json` | The narration, scene by scene, in caption-sized lines, and the voice settings |
| `scripts/voice.mjs` | ElevenLabs text to speech with timestamps, one request per scene, cached in `voice/cache`; assembles one continuous track |
| `src/timing.json` | The narration's timing, which every cut, zoom and caption follows |
| `src/` | The composition: scenes, transitions, the footage camera, cursor, terminals and captions |

Each take is a folder of frames in `public/captures/<take>/` with `take.json`: when each frame was painted, and every
pointer sample, click, key and named element rectangle. The composition draws the cursor and click ripples from that
log, time-warps the footage so each action lands on the word that names it, and springs the camera into the rectangle
being discussed. `node capture/inspect.mjs <take> [seconds...]` lists a take's events and frames.

### Continuous narration

`scripts/voice.mjs` cuts every line out of its scene's audio where the voice really starts and stops (measured on the
audio, since ElevenLabs stretches a line's last character to the next line's first), gates every pause of 0.25 s or
more to one clean silence (so no breath or word fragment is left inside it), shortens a pause inside a line to 0.3 s,
and starts each line 0.28 s after the previous one's last sound. The one longer pause, 0.75 s, is before the results.

Then the assembled track is checked at the level the finished track will have, and cut where needed (always in the
middle of a silence, with every time in the timing moved to match): no pause over 0.36 s, and no two pauses of 0.15 s
or more within 0.5 s of each other (the shorter one, preferring a pause inside a line over one between lines, goes
under 0.15 s). The track is loudness-matched to -16 LUFS as a whole, with an even room tone at about -66 dBFS under
it. Scenes are placed on the track, and each transition plays under the end of one line and the start of the next,
so the picture never waits for the voice. Check it with:

```sh
node scripts/pauses.mjs                 # silencedetect -35 dB, 0.15 s: pairs within 0.5 s, or a stretch over 0.4 s
ffmpeg -i out/airspace-demo.mp4 -af silencedetect=noise=-40dB:d=0.4 -f null -
```

### Terminals

The agent terminals are drawn as Claude Code prints a session: `● Update(path)` for an edit, its diff, and the hook's
answer under `⎿` in plain monospace, coloured the way a terminal colours it (symbols bold, the new signature green, the
old one red, the path amber). When the voice names a part of a hold, a highlight sweeps behind those words. Nothing in
the film is boxed, bordered or badged for decoration; the footage's own UI is the site's.

### Transitions

Three families, all Airspace's own marks: the radar **sweep** (the beam turns once and paints the next scene in behind
it), the **lens** (two airspaces close over the outgoing scene, their overlap turns orange as in the logo, and the lens
opens out into the next section), and the **flight path** (a track is drawn across the frame and the scenes travel along
it).

## Re-record

Public takes (`hero`, `tower`, `preflight`, `playground`) record https://airspace.sushans.dev and change nothing there.

```sh
cd video && node capture/run.mjs hero tower preflight playground
```

Signed-in takes record a local stack against the `airspace-falkordb-1` container (`docker compose up -d falkordb`),
with graphs of their own: `airspace_accounts_video`, the workspace's graph, and `airspace_video_local`.

```sh
cd server && uv sync && cd ../web && npm ci && cd ../video
mkdir -p .stack-data/config .stack-data/cache && cp -R ../server/tests/fixtures/blog .stack-data/blog
python3 -c "import secrets;print(secrets.token_hex(32))" > .stack-data/secret
node capture/stack.mjs api &            # airspace serve on :8810
node capture/stack.mjs web &            # Vite on :4210, proxying to :8810
node capture/stack.mjs run uv run --project server python video/capture/signin.py
node capture/run.mjs workspace          # creates the workspace, connects .stack-data/blog, installs the hooks
node capture/run.mjs wstower wsmemory   # the run, through the real hooks, while Tower records
```

After re-recording, check each take's times (`node capture/inspect.mjs <take>`) against the warps in `src/scenes`.
Afterwards, delete what the stack made: `GRAPH.DELETE` the three graphs above, and `.stack-data`.

## Re-voice

`npm run voice` reads `ELEVENLABS_API_KEY` from the environment or the `export` line in `~/.zshrc` (never printed),
and calls `POST /v1/text-to-speech/{voice}/with-timestamps` once per scene with the model and voice in
`narration/script.json` (Eric, `eleven_v4`). A scene is generated again only when its text or the voice settings
change; the cache is committed. Gaps and pauses are applied when the track is assembled, so pacing changes cost
nothing. `npm run voice:draft` uses macOS `say` instead (writes files, plays nothing).

## Re-render and review

```sh
npm run render                          # about 8 minutes on an M-series Mac
npm run still -- --scenes               # three stills per scene, to out/stills
npm run still -- --transitions          # the middle of every transition
npm run still -- 42.5 97                # those seconds
node scripts/frames.mjs 60:tower        # a frame of the rendered mp4, to out/final-stills
```

Everything renders headless and silent.

## Licence

Remotion is free for individuals and for companies of up to three people, which covers this project; larger teams
need a company licence (see [remotion.dev/license](https://www.remotion.dev/license)). Schibsted Grotesk and
JetBrains Mono are under the SIL Open Font License. There is no music.
