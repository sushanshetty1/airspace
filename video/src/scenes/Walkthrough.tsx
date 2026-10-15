// The product, recorded: each scene says what a feature does, then the footage proves it, the camera springing to
// exactly the thing the voice names. Times are scene seconds; take times come from each take's log
// (node capture/inspect.mjs <take>).

import { AbsoluteFill } from 'remotion'
import { C } from '../brand'
import { Clip } from '../components/Clip'
import { Terminal, pop, useSec, type TermLine } from '../components/ui'
import { useSceneTime } from '../timeline'
import hooks from '../data/hooks.json'

const FULL = null

/** What the hook told agent-c: the fix, from the run's own hook log (capture/session.py). */
const FIX_TOLD = (hooks as { step: string; kind: string; out: { hookSpecificOutput?: { additionalContext?: string } } | null }[]).find((h) => h.step === 'c-start')!.out!.hookSpecificOutput!.additionalContext!

export function Preflight() {
  const { c, word, dur, inEnd } = useSceneTime()
  const tasks = { x: 232, y: 70, w: 463, h: 830 }
  const result = { x: 720, y: 72, w: 648, h: 828 }
  const summary = { x: 744, y: 128, w: 600, h: 70 }
  const groups = { x: 744, y: 210, w: 600, h: 192 }
  const meet = { x: 744, y: 438, w: 600, h: 228 }
  const deps = { x: 744, y: 704, w: 280, h: 196 }
  return (
    <Clip
      take="preflight"
      from={0}
      to={dur}
      warp={[
        [0, 20.45],
        [c(1) - 0.2, 22.2],
        [c(1) + 1.4, 23.95],
        [dur, 23.95 + (dur - c(1) - 1.4) * 0.6],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: inEnd - 0.3, rect: { x: 180, y: 90, w: 900, h: 420 }, stiffness: 30 },
        { at: c(1) + 0.9, rect: tasks, pad: 20 },
        { at: word('milliseconds', c(1)) - 0.2, rect: summary, pad: 40, max: 2.0 },
        { at: c(2) - 0.1, rect: groups, pad: 30 },
        { at: word('path', c(2)) - 0.2, rect: meet, pad: 30 },
        { at: word('traversal', c(3)) - 0.5, rect: deps, pad: 60, max: 2.0 },
        { at: word('components', c(3)) - 0.4, rect: groups, pad: 50, max: 2.0 },
        { at: word('shortest', c(3)) - 0.4, rect: meet, pad: 50, max: 2.0 },
        { at: word('Falkor', c(3)) - 0.1, rect: result, pad: 16 },
      ]}
      rings={[
        { at: word('five', c(1)), until: word('milliseconds', c(1)) - 0.3, rect: { x: 244, y: 120, w: 440, h: 760 }, pad: 4 },
        { at: word('coordinate', c(2)) - 0.1, until: word('path', c(2)) - 0.3, rect: { x: 746, y: 212, w: 290, h: 188 }, color: C.accent, pad: 4 },
        { at: word('free', c(2)) - 0.2, until: c(3) - 0.3, rect: { x: 1050, y: 212, w: 292, h: 188 }, color: C.ok, pad: 4 },
        { at: word('traversal', c(3)) - 0.1, until: word('components', c(3)) - 0.5, rect: deps, label: '[:CALLS|COVERS|INHERITS*1..2]', below: false, pad: 6 },
        { at: word('components', c(3)) - 0.05, until: word('shortest', c(3)) - 0.5, rect: groups, label: 'algo.WCC', below: true, pad: 6 },
        { at: word('shortest', c(3)) - 0.05, until: dur, rect: meet, label: 'shortestPath', below: true, pad: 6 },
      ]}
      cursor={false}
    />
  )
}

export function Memory() {
  const { sec, fps } = useSec()
  const { c, word, dur } = useSceneTime()
  const switchAt = c(1) - 0.3
  const written = { x: 1222, y: 398, w: 378, h: 214 }
  const memItem = { x: 12, y: 664, w: 255, h: 224 }
  const term = pop(sec, c(1) + 0.15, fps)
  const lines: TermLine[] = [
    { at: c(1) + 0.3, kind: 'prompt', cps: 70, text: 'Make post_list in blog/views.py link each post by its slug.' },
    { at: word('told', c(1)) - 0.35, kind: 'status', text: 'UserPromptSubmit hook additional context:' },
    {
      at: word('told', c(1)) - 0.2,
      kind: 'body',
      text: FIX_TOLD,
      tokens: [
        { text: 'utils.text.slugify', color: C.text, bold: true },
        { text: 'slugify(post.title, allow_unicode=True)', color: '#ff9b9b' },
        { text: 'slugify(value, *, unicode=False)', color: '#8fe0b5' },
        { text: 'slugify(post.title, unicode=True)', color: '#8fe0b5' },
      ],
      marks: [{ text: 'slugify(post.title, unicode=True)', at: word('fix', c(1)) - 0.1 }],
    },
    { at: word('writes', c(1)) + 0.1, kind: 'tool', text: 'Update(blog/views.py)' },
    { at: word('call', c(1)) + 0.1, kind: 'add', text: '<li id="{slugify(p.title)}">' },
  ]
  return (
    <AbsoluteFill>
      <Clip
        take="wstower"
        from={0}
        to={switchAt}
        exit
        warp={[
          [0, 20.6],
          [word('clears', c(0)), 21.6],
          [word('written', c(0)) + 0.2, 23.2],
          [switchAt + 0.6, 24.5],
        ]}
        shots={[
          { at: 0, rect: { x: 360, y: 52, w: 1240, h: 640 } },
          { at: word('written', c(0)) - 0.1, rect: written, pad: 24, max: 2.4 },
        ]}
        rings={[{ at: word('graph', c(0)), until: switchAt, rect: written, color: C.ok, pad: 4 }]}
        cursor={false}
      />
      <Clip
        take="wsmemory"
        from={switchAt}
        to={dur}
        enter
        warp={[
          [switchAt, 1.2],
          [switchAt + 1.6, 3.4],
          [dur, 3.4 + (dur - switchAt - 1.6) * 0.8],
        ]}
        shots={[
          { at: switchAt, rect: { x: 0, y: 52, w: 700, h: 848 } },
          { at: switchAt + 1.4, rect: { x: 0, y: 560, w: 560, h: 340 }, max: 2.0 },
        ]}
        rings={[{ at: switchAt + 2.0, until: dur, rect: memItem, color: C.ok, pad: 4 }]}
      />
      <div style={{ position: 'absolute', left: 900, top: 380, width: 840, opacity: Math.min(1, term * 1.4), transform: `translateY(${(1 - term) * 60}px)` }}>
        <Terminal
          title={
            <span>
              <span style={{ color: C.c, fontWeight: 600 }}>agent-c</span> · Claude Code · a later session
            </span>
          }
          color={C.c}
          lines={lines}
          sec={sec}
          style={{ height: 400 }}
          size={17}
        />
      </div>
    </AbsoluteFill>
  )
}

export function Playground() {
  const { c, word, dur } = useSceneTime()
  const fieldsA = { x: 232, y: 158, w: 560, h: 270 }
  const fieldsB = { x: 808, y: 158, w: 560, h: 270 }
  const verdict = { x: 233, y: 196, w: 1134, h: 470 }
  return (
    <Clip
      take="playground"
      from={0}
      to={dur}
      warp={[
        [0, 0.9],
        [c(0) + 0.4, 2.05],
        [c(1) - 0.3, 5.6],
        [c(1) - 0.3, 10.9],
        [word('write', c(1)) - 0.1, 11.7],
        [word('engine', c(1)) - 0.3, 15.35],
        [word('verdict', c(1)), 16.6],
        [word('path', c(1)) + 0.1, 18.0],
        [dur, 18.0 + (dur - word('path', c(1)) - 0.1) * 0.8],
      ]}
      shots={[
        { at: 0, rect: FULL },
        { at: c(0) + 1.0, rect: verdict, pad: 20 },
        { at: c(1) - 0.3, rect: fieldsA, pad: 30 },
        { at: word('write', c(1)) - 0.2, rect: fieldsB, pad: 30 },
        { at: word('verdict', c(1)) - 0.1, rect: verdict, pad: 20 },
      ]}
      rings={[{ at: word('path', c(1)) + 0.15, until: dur, rect: { x: 255, y: 340, w: 360, h: 44 }, color: C.ok, pad: 8 }]}
    />
  )
}

export function Workspaces() {
  const { sec, fps } = useSec()
  const { c, word, dur } = useSceneTime()
  const termAt = c(1) - 0.1
  const towerAt = c(1) + 2.9
  const term = pop(sec, termAt, fps) * (sec < towerAt + 0.6 ? 1 : 0)
  const keyMasks = [
    { rect: { x: 266, y: 372, w: 520, h: 30 }, from: 3.5 },
    { rect: { x: 280, y: 500, w: 360, h: 28 }, from: 3.5 },
    { rect: { x: 252, y: 734, w: 110, h: 26 }, from: 3.5 },
  ]
  const lines: TermLine[] = [
    { at: termAt + 0.2, kind: 'cmd', cps: 60, text: 'uv run airspace connect --root . --server http://localhost:8810 --key ask_••••••••' },
    { at: termAt + 1.6, kind: 'out', text: 'Connected …/blog to workspace f06cd8b648d9 on http://localhost:8810' },
    { at: termAt + 1.9, kind: 'out', text: 'Indexed 13 files, 17 symbols, 15 calls (9 unresolved)' },
    { at: termAt + 2.1, kind: 'out', text: 'Tower: http://localhost:8810/w/f06cd8b648d9' },
  ]
  const release = { x: 1241, y: 618, w: 131, h: 36 }
  const pause = { x: 1381, y: 618, w: 139, h: 36 }
  const message = { x: 1241, y: 412, w: 340, h: 150 }
  return (
    <AbsoluteFill>
      <Clip
        take="workspace"
        from={0}
        to={towerAt}
        exit
        warp={[
          [0, 0.6],
          [c(0) + 1.4, 1.9],
          [word('workspace', c(0)) + 0.1, 3.6],
          [towerAt + 0.6, 6.5],
        ]}
        shots={[
          { at: 0, rect: FULL },
          { at: word('create', c(0)) - 0.5, rect: { x: 220, y: 100, w: 860, h: 640 } },
          { at: word('workspace', c(0)) + 0.4, rect: { x: 250, y: 280, w: 800, h: 520 } },
        ]}
        rings={[{ at: word('GitHub', c(0)) - 0.2, until: word('create', c(0)) - 0.4, rect: { x: 1334, y: 16, w: 34, h: 34 }, pad: 6 }]}
        masks={keyMasks}
        labels={[{ at: 0.6, until: c(1) - 0.3, title: 'Workspaces', sub: 'The hosted app, run locally for this recording' }]}
      />
      <div style={{ position: 'absolute', left: 230, top: 560, width: 1460, opacity: Math.min(1, term * 1.4), transform: `translateY(${(1 - term) * 50}px)` }}>
        <Terminal title={<span>~/blog · zsh</span>} color={C.muted} lines={lines} sec={sec} style={{ height: 200 }} size={18} />
      </div>
      <Clip
        take="wstower"
        from={towerAt}
        to={dur}
        enter
        warp={[
          [towerAt, 1.2],
          [c(2), 5.5],
          [c(3) - 0.4, 9.6],
          [word('release', c(3)) - 0.1, 10.9],
          [word('pause', c(3)) - 0.1, 12.0],
          [word('message', c(3)), 13.6],
          [dur, 13.6 + (dur - word('message', c(3)))],
        ]}
        shots={[
          { at: towerAt, rect: FULL },
          { at: c(2) + 0.6, rect: { x: 300, y: 52, w: 1000, h: 640 } },
          { at: c(3) - 0.3, rect: { x: 1150, y: 52, w: 450, h: 640 }, max: 2.0 },
        ]}
        rings={[
          { at: word('release', c(3)), until: word('pause', c(3)) - 0.05, rect: release, color: C.text, pad: 5 },
          { at: word('pause', c(3)), until: word('message', c(3)) - 0.05, rect: pause, color: C.text, pad: 5 },
          { at: word('message', c(3)), until: dur, rect: message, color: C.text, pad: 5 },
        ]}
        labels={[{ at: towerAt + 0.5, until: c(3) - 0.5, title: 'Your workspace, live', sub: 'Two sessions through the real hooks: one held at slugify' }]}
      />
    </AbsoluteFill>
  )
}
