// The problem, from a real benchmark run (server/bench/results/final/slugify-keyword-only--worktrees--r1.json):
// each agent's branch passes its own tests; the merge fails with the TypeError the merged test run printed.
// Then the measured result for worktrees alone: 0 of 18 merges green.

import { AbsoluteFill, interpolate } from 'remotion'
import { C, MONO, SANS, ease, easeInOut } from '../brand'
import { Sign, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'

const MAIN_Y = 500
const A_Y = 290
const B_Y = 710
const SPLIT_A = 250
const SPLIT_B = 300
const MERGE = 1290

function Branch({ y, from, color, p }: { y: number; from: number; color: string; p: number }) {
  const d = `M${from} ${MAIN_Y} C ${from + 70} ${MAIN_Y}, ${from + 70} ${y}, ${from + 150} ${y} H ${MERGE - 150} C ${MERGE - 70} ${y}, ${MERGE - 70} ${MAIN_Y}, ${MERGE} ${MAIN_Y}`
  const len = 1700
  return <path d={d} fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - p)} />
}

function Mark({ children, on }: { children: string; on: number }) {
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <span style={{ position: 'absolute', left: -3, right: -3, top: 1, bottom: 1, borderRadius: 4, background: C.accent, transform: `scaleX(${on})`, transformOrigin: 'left center' }} />
      <span style={{ position: 'relative', color: on > 0.5 ? C.accentInk : undefined }}>{children}</span>
    </span>
  )
}

function BranchCard({ x, y, color, agent, branch, lines, pass, mark }: { x: number; y: number; color: string; agent: string; branch: string; lines: { sign: '+' | '-'; parts: (string | { mark: string })[] }[]; pass: number; mark: number }) {
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: 760, background: C.surface, borderRadius: 14, boxShadow: `0 30px 70px -30px rgba(0,0,0,0.9), inset 0 0 0 1px ${C.line}`, overflow: 'hidden' }}>
      <div style={{ height: 46, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 18px', borderBottom: `1px solid ${C.line}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontFamily: SANS, fontSize: 17 }}>
          <span style={{ fontFamily: MONO, color, fontWeight: 600 }}>{agent}</span>
          
          <span style={{ color: C.muted }}>{branch}</span>
        </div>
        <div style={{ opacity: pass, transform: `scale(${0.8 + 0.2 * pass})` }}>
          <Sign kind="cleared">3 tests pass</Sign>
        </div>
      </div>
      <div style={{ padding: '14px 18px 16px', fontFamily: MONO, fontSize: 18.5, lineHeight: 1.75 }}>
        {lines.map((l, i) => (
          <div key={i} style={{ color: l.sign === '+' ? '#8fe0b5' : '#ff9b9b', background: l.sign === '+' ? 'rgba(60,207,142,0.07)' : 'rgba(255,93,93,0.07)', padding: '0 10px', borderRadius: 5, whiteSpace: 'pre' }}>
            {l.sign} {l.parts.map((p, k) => (typeof p === 'string' ? <span key={k}>{p}</span> : <Mark key={k} on={mark}>{p.mark}</Mark>))}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Open() {
  const { sec, fps } = useSec()
  const { c, word } = useSceneTime()

  const mainP = ramp(sec, 0.1, 0.9, easeInOut)
  const aP = ramp(sec, 0.35, 1.3, easeInOut)
  const bP = ramp(sec, 0.6, 1.3, easeInOut)
  const cardA = pop(sec, 0.75, fps)
  const cardB = pop(sec, 1.05, fps)
  const passA = pop(sec, word('passes') - 0.05, fps, { damping: 12, stiffness: 200, mass: 0.6 })
  const passB = pop(sec, word('passes') + 0.15, fps, { damping: 12, stiffness: 200, mass: 0.6 })

  // Merge: the branches run into main, and main after the merge turns red.
  const mergeAt = word('Merge', c(1) - 0.3) - 0.1
  const merged = ramp(sec, mergeAt, 0.7, easeInOut)
  const red = ramp(sec, word('red', mergeAt) - 0.25, 0.5)
  const fail = pop(sec, word('red', mergeAt) - 0.1, fps)

  // The cause: what A changed and what B still calls.
  const markOn = ramp(sec, word('changed', c(2)) - 0.1, 0.4)
  const markB = ramp(sec, word('calling', c(2)) - 0.1, 0.4)
  const arc = ramp(sec, word('calling', c(2)) + 0.1, 0.7, easeInOut)

  // The measured result.
  const statAt = c(3) - 0.15
  const back = ramp(sec, statAt, 0.7)
  const stat = pop(sec, word('measured', statAt) - 0.1, fps, { damping: 16, stiffness: 120, mass: 0.9 })
  const zero = pop(sec, word('zero', statAt) - 0.05, fps, { damping: 11, stiffness: 180, mass: 0.7 })

  const shift = interpolate(merged, [0, 1], [0, 0], clamp)
  void shift

  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ opacity: 1 - back * 0.82, transform: `scale(${1 - back * 0.06}) translateY(${-back * 30}px)`, filter: `blur(${back * 3}px)` }}>
        <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0 }}>
          <text x={150} y={MAIN_Y - 18} fill={C.muted} fontFamily={MONO} fontSize={18} fontWeight={600} opacity={mainP}>
            main
          </text>
          <line x1={150} y1={MAIN_Y} x2={150 + (MERGE - 150) * mainP} y2={MAIN_Y} stroke={C.lineStrong} strokeWidth={3} />
          <Branch y={A_Y} from={SPLIT_A} color={C.a} p={aP * (0.86 + 0.14 * merged)} />
          <Branch y={B_Y} from={SPLIT_B} color={C.b} p={bP * (0.86 + 0.14 * merged)} />
          <line x1={MERGE} y1={MAIN_Y} x2={MERGE + 480 * red} y2={MAIN_Y} stroke={C.bad} strokeWidth={3.5} strokeDasharray="10 9" />
          <circle cx={MERGE} cy={MAIN_Y} r={11 * merged} fill={red > 0.5 ? C.bad : C.text} />
          <circle cx={MERGE} cy={MAIN_Y} r={11 + 26 * red} fill="none" stroke={C.bad} strokeOpacity={(1 - red) * 0.7} strokeWidth={2} />
          {/* B's call reaches for the signature A no longer has. */}
          <path
            d={`M 760 ${B_Y - 30} C 640 ${MAIN_Y + 40}, 640 ${MAIN_Y - 40}, 700 ${A_Y + 60}`}
            fill="none"
            stroke={C.accent}
            strokeWidth={3}
            strokeDasharray="8 8"
            pathLength={1}
            opacity={arc}
            style={{ strokeDasharray: `${arc} 1` }}
          />
        </svg>
        <div style={{ opacity: Math.min(1, cardA * 1.5), transform: `translateY(${(1 - cardA) * 30}px)` }}>
          <BranchCard
            x={400}
            y={A_Y - 74}
            color={C.a}
            agent="agent-a"
            branch="on its own branch"
            pass={passA}
            mark={markOn}
            lines={[
              { sign: '-', parts: ['def slugify(value, ', { mark: 'allow_unicode' }, '=False):'] },
              { sign: '+', parts: ['def slugify(value, *, unicode=False):'] },
            ]}
          />
        </div>
        <div style={{ opacity: Math.min(1, cardB * 1.5), transform: `translateY(${(1 - cardB) * 30}px)` }}>
          <BranchCard
            x={440}
            y={B_Y - 56}
            color={C.b}
            agent="agent-b"
            branch="on its own branch"
            pass={passB}
            mark={markB}
            lines={[{ sign: '+', parts: ['slug = slugify(post.title, ', { mark: 'allow_unicode' }, '=True)'] }]}
          />
        </div>
        <div
          style={{
            position: 'absolute',
            left: MERGE + 40,
            top: MAIN_Y - 196,
            width: 440,
            background: C.surface,
            borderRadius: 14,
            boxShadow: `0 30px 70px -30px rgba(0,0,0,0.9), inset 0 0 0 1px rgba(255,93,93,0.35)`,
            padding: '16px 18px 18px',
            opacity: Math.min(1, fail * 1.4),
            transform: `translateY(${(1 - fail) * 24}px)`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: SANS, fontSize: 17, color: C.text }}>
            <span>
              <span style={{ fontFamily: MONO, color: C.muted }}>main</span> after the merge
            </span>
            <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 15, color: C.bad, background: C.badSoft, padding: '3px 9px', borderRadius: 6 }}>Failed</span>
          </div>
          <div style={{ marginTop: 12, fontFamily: MONO, fontSize: 15.5, lineHeight: 1.55, color: '#ffb1b1', whiteSpace: 'pre-wrap' }}>
            {'TypeError: slugify() got an\nunexpected keyword argument\n'}
            <span style={{ color: C.text }}>'allow_unicode'</span>
          </div>
          <div style={{ marginTop: 8, fontFamily: MONO, fontSize: 14, color: C.faint }}>blog/views.py:7 in render_post</div>
        </div>
      </AbsoluteFill>

      {/* 0 of 18. */}
      <AbsoluteFill style={{ opacity: Math.min(1, stat * 1.6), transform: `translateY(${(1 - stat) * 40}px)` }}>
        <div style={{ position: 'absolute', left: 0, right: 0, top: 230, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 196, letterSpacing: '-0.055em', lineHeight: 1, color: C.text, transform: `scale(${0.82 + 0.18 * zero})` }}>
            0 <span style={{ color: C.faint, fontSize: 120 }}>of</span> 18
          </div>
          <div style={{ marginTop: 22, fontFamily: SANS, fontSize: 34, fontWeight: 500, color: C.text, letterSpacing: '-0.015em' }}>merges green, with worktrees alone</div>
          <div style={{ marginTop: 34, display: 'grid', gridTemplateColumns: 'repeat(18, 46px)', gap: 12 }}>
            {Array.from({ length: 18 }, (_, k) => {
              const q = ramp(sec, word('zero', statAt) + 0.1 + k * 0.035, 0.3)
              return <div key={k} style={{ height: 46, borderRadius: 9, boxShadow: `inset 0 0 0 2px ${C.bad}`, background: C.badSoft, opacity: q, transform: `scale(${0.6 + 0.4 * q})` }} />
            })}
          </div>
          <div style={{ marginTop: 28, fontFamily: SANS, fontSize: 21, color: C.muted }}>Two real Claude Code agents per pair, six kinds of change, three runs each</div>
        </div>
      </AbsoluteFill>
      {void ease}
    </AbsoluteFill>
  )
}
