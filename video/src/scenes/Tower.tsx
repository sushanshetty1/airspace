// Tower, the session view, recorded from the live site's replay of a real run (the `tower` take). The replay has
// no terminals, so the two Claude Code sessions are drawn beside it from the same run's record: the prompts from
// docs/demo-script.md, the edits from the replay's events and the benchmark's diffs, and the hold text the edit
// tool returned to agent-b (README.md), each line arriving when the replay shows that event.

import { AbsoluteFill, interpolate, spring } from 'remotion'
import { C, SANS, SLAB } from '../brand'
import { Footage, FootageFrame, type Warp } from '../components/Footage'
import { Terminal, clamp, useSec, type TermLine } from '../components/ui'
import { useSceneTime } from '../timeline'

const HOLD_TEXT =
  'Airspace hold: utils.text.slugify is being changed by agent-a. New signature: slugify(value, *, unicode=False) (was slugify(value, allow_unicode=False)). This edit adds a call to it from blog.views.render_post. The call blog.views.render_post makes does not fit the new signature. Path: blog.views.render_post -> utils.text.slugify. A retry whose call matches the new signature will be cleared.'

const SPLIT = { x: 700, w: 1180 }
const TERM = { x: 40, w: 630 }

export function TowerScene() {
  const { sec, fps } = useSec()
  const { c, word, dur } = useSceneTime()

  // The layout opens to make room for the agents' terminals when the voice turns to agent-a.
  const splitAt = c(2) - 0.35
  const s = spring({ frame: (sec - splitAt) * fps, fps, config: { damping: 22, stiffness: 90, mass: 1 } }) * (sec > splitAt ? 1 : 0)
  const k = interpolate(s, [0, 1], [1, SPLIT.w / SLAB.w])
  const box = {
    x: interpolate(s, [0, 1], [SLAB.x, SPLIT.x]),
    y: SLAB.y + (SLAB.h - SLAB.h * k) / 2,
    w: SLAB.w * k,
  }
  const termIn = (d: number) => spring({ frame: (sec - splitAt - d) * fps, fps, config: { damping: 20, stiffness: 100, mass: 0.9 } }) * (sec > splitAt + d ? 1 : 0)

  const cleared = word('cleared', c(6))
  const land = word('land', c(6))
  const warp: Warp = [
    [0, 0.4],
    [c(3) - 1.0, 1.25],
    [c(4) - 0.1, 4.8],
    [c(4) + 1.4, 5.8],
    [c(5) - 0.8, 5.9],
    [c(5) - 0.8, 8.7],
    [c(5) + 0.4, 10.3],
    [c(6) - 0.6, 16.7],
    [c(6) + 0.3, 17.4],
    [cleared - 0.25, 22.05],
    [land + 0.4, 24.6],
    [dur, 24.6 + (dur - land - 0.4) * 0.6],
  ]

  // Every label of the radar stays inside the frame: test_render_post reaches x 552, agent-b's airspace x 1331.
  const radar = { x: 540, y: 165, w: 800, h: 430 }
  const aSpace = { x: 540, y: 170, w: 540, h: 430 }
  const panel = { x: 1221, y: 120, w: 379, h: 330 }
  const sigs = { x: 1233, y: 318, w: 360, h: 110 }

  // Terminal colours, as a terminal sets them: symbols bold, the new signature green, the old red, the path amber.
  const holdTokens = [
    { text: 'utils.text.slugify', color: C.text, bold: true },
    { text: 'blog.views.render_post', color: C.text, bold: true },
    { text: 'slugify(value, *, unicode=False)', color: '#8fe0b5' },
    { text: 'slugify(value, allow_unicode=False)', color: '#ff9b9b' },
    { text: 'blog.views.render_post -> utils.text.slugify', color: '#e8c48a' },
    { text: 'agent-a', color: C.a },
  ]
  const linesA: TermLine[] = [
    { at: c(2) + 0.1, kind: 'prompt', cps: 95, text: 'In utils/text.py, make the unicode option of slugify keyword-only and rename it, so the signature is exactly slugify(value, *, unicode=False). Update the body and every caller.' },
    { at: c(2) + 2.3, kind: 'tool', text: 'Update(utils/text.py)' },
    { at: c(2) + 2.6, kind: 'del', text: 'def slugify(value, allow_unicode=False):' },
    { at: c(2) + 2.75, kind: 'add', text: 'def slugify(value, *, unicode=False):' },
    { at: c(2) + 4.0, kind: 'tool', text: 'Bash(pytest -q)' },
    { at: c(2) + 4.5, kind: 'status', text: '3 passed' },
    { at: c(5) + 4.2, kind: 'say', text: 'slugify is now slugify(value, *, unicode=False), and all 3 tests pass.' },
  ]
  const linesB: TermLine[] = [
    { at: c(3) - 0.2, kind: 'prompt', cps: 95, text: 'In blog/views.py, make render_post add a data-slug attribute to the article tag, built as slugify(post.title, allow_unicode=True).' },
    { at: c(3) + 1.5, kind: 'tool', text: 'Update(blog/views.py)' },
    { at: c(3) + 1.8, kind: 'add', text: 'slug = slugify(post.title, allow_unicode=True)' },
    { at: word('held', c(4)) - 0.15, kind: 'status', text: 'PreToolUse:Edit hook blocked:', color: '#e8836a' },
    {
      at: word('held', c(4)) + 0.05,
      kind: 'body',
      text: HOLD_TEXT,
      tokens: holdTokens,
      marks: [
        { text: 'agent-a', at: word('who', c(5)) },
        { text: 'slugify(value, *, unicode=False)', at: word('signature', c(5)) - 0.1 },
        { text: 'blog.views.render_post -> utils.text.slugify', at: word('path', c(5)) - 0.1 },
      ],
    },
    { at: c(6) + 0.25, kind: 'tool', text: 'Update(blog/views.py)' },
    { at: c(6) + 0.55, kind: 'add', text: 'slug = slugify(post.title, unicode=True)' },
    { at: land + 0.2, kind: 'say', text: "I changed the call in render_post to slugify(post.title, unicode=True) to match agent-a's new keyword-only signature." },
  ]

  const a = termIn(0.05)
  const b = termIn(0.2)
  const termH = 438

  return (
    <AbsoluteFill>
      <FootageFrame box={box}>
        <Footage
          take="tower"
          warp={warp}
          shots={[
            { at: 0, rect: null },
            { at: c(2) + 0.3, rect: aSpace, pad: 20, stiffness: 55 },
            { at: c(3) + 0.4, rect: radar, pad: 24 },
            { at: c(4) + 0.1, rect: radar, pad: 14 },
            { at: c(5) - 0.85, rect: { x: 330, y: 110, w: 1270, h: 520 }, pad: 10 },
            { at: c(5) + 0.45, rect: panel, pad: 24, max: 2.2 },
            { at: c(6) + 0.2, rect: { x: 330, y: 110, w: 1270, h: 520 }, pad: 10 },
            { at: land + 0.6, rect: null, stiffness: 40 },
          ]}
          rings={[
            { at: c(0) + 1.0, until: c(1) - 0.2, rect: { x: 12, y: 62, w: 158, h: 30 }, pad: 6 },
            { at: c(1) + 0.4, until: c(2) - 0.4, rect: { x: 10, y: 290, w: 262, h: 270 }, pad: 6 },
            { at: word('signature', c(5)) - 0.1, until: c(6) - 0.2, rect: sigs, color: C.accent, pad: 6 },
            { at: cleared + 0.1, until: dur - 0.6, rect: { x: 745, y: 336, w: 92, h: 40 }, color: C.ok, pad: 8 },
          ]}
        />
      </FootageFrame>

      <div style={{ position: 'absolute', left: TERM.x, top: SLAB.y, width: TERM.w, opacity: Math.min(1, a * 1.4), transform: `translateX(${(1 - a) * -120}px)` }}>
        <Terminal title={<span><span style={{ color: C.a, fontWeight: 600 }}>agent-a</span> · Claude Code · its own worktree</span>} color={C.a} lines={linesA} sec={sec} style={{ height: termH }} size={15.5} />
      </div>
      <div style={{ position: 'absolute', left: TERM.x, top: SLAB.y + termH + 24, width: TERM.w, opacity: Math.min(1, b * 1.4), transform: `translateX(${(1 - b) * -120}px)` }}>
        <Terminal title={<span><span style={{ color: C.b, fontWeight: 600 }}>agent-b</span> · Claude Code · its own worktree</span>} color={C.b} lines={linesB} sec={sec} style={{ height: termH }} size={15.5} />
      </div>
      <div style={{ position: 'absolute', left: SPLIT.x, top: SLAB.y + SLAB.h - 70, fontFamily: SANS, fontSize: 16, color: C.faint, opacity: interpolate(s, [0.6, 1], [0, 1], clamp) }}>
        Tower on airspace.sushans.dev: the replay of a real run
      </div>
    </AbsoluteFill>
  )
}
