// The benchmark, from web/src/data/benchmark-flask.json and README.md: Flask, three changes to its public API,
// three runs each, graded by Flask's own tests plus a hidden test per agent. Airspace's row lands last.

import { AbsoluteFill, interpolate } from 'remotion'
import { C, MONO, SANS, ease } from '../brand'
import { clamp, pop, ramp, useSec } from '../components/ui'
import flask from '../data/benchmark-flask.json'
import { useSceneTime } from '../timeline'

type Cond = 'worktrees' | 'broadcast' | 'airspace'
const SET_NAMES: Record<string, string> = {
  'flask-flash-categories': 'get_flashed_messages',
  'flask-debug-rename': 'get_debug_flag',
  'flask-send-file-name': 'send_file',
}
const data = flask as unknown as { conditions: Record<Cond, { merged_pass: number; median_wall_seconds: number }>; sets: Record<string, Record<Cond, boolean[]>> }
const setIds = Object.keys(data.sets)
const ROWS: { id: Cond; name: string; sub: string }[] = [
  { id: 'worktrees', name: 'Worktrees only', sub: 'each agent on its own branch' },
  { id: 'broadcast', name: 'Broadcast', sub: "each agent told the other's task" },
  { id: 'airspace', name: 'Airspace', sub: 'clearance, briefings, the holding pattern' },
]

export function Numbers() {
  const { sec, fps } = useSec()
  const { c, word, inEnd } = useSceneTime()
  const head = ramp(sec, inEnd - 0.6, 0.6)
  const rowAt: Record<Cond, number> = { worktrees: c(1) - 0.1, broadcast: c(2) - 0.1, airspace: word('nine', c(3) - 0.1) - 0.35 }
  const sampleAt = c(4) - 0.1
  const timesAt = word('slower', c(5)) - 0.2
  const shipAt = word('merge', c(5)) - 0.2

  const land = pop(sec, rowAt.airspace + 0.25, fps, { damping: 9, stiffness: 210, mass: 0.75 })
  const ping = interpolate(sec, [rowAt.airspace + 0.25, rowAt.airspace + 1.3], [0, 1], clamp)
  const ship = ramp(sec, shipAt, 0.5)

  const ROW_Y = 330
  const ROW_H = 150
  const SQ = 60
  const GX = 760

  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', left: 160, top: 60, opacity: head, transform: `translateY(${(1 - head) * 14}px)` }}>
        <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 56, letterSpacing: '-0.035em', color: C.text }}>Flask, with real Claude Code agents</div>
        <div style={{ marginTop: 10, fontFamily: SANS, fontSize: 23, color: C.muted }}>
          83 files, 894 symbols. Graded on the merge of both branches, by Flask&rsquo;s own 491 tests plus a hidden test per agent.
        </div>
      </div>

      {/* Which change agent A made, three runs each. */}
      <div style={{ position: 'absolute', left: GX, top: ROW_Y - 62, display: 'flex', gap: 30, opacity: ramp(sec, rowAt.worktrees - 0.2, 0.5) }}>
        {setIds.map((s) => (
          <div key={s} style={{ width: SQ * 3 + 12 * 2, fontFamily: MONO, fontSize: 16.5, color: C.muted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {SET_NAMES[s] ?? s}
          </div>
        ))}
      </div>

      {ROWS.map((row, r) => {
        const at = rowAt[row.id]
        const show = ramp(sec, at, 0.5)
        const isA = row.id === 'airspace'
        const n = data.conditions[row.id].merged_pass
        const highlight = isA ? Math.max(land * 0.9, ship) : 0
        return (
          <div key={row.id} style={{ position: 'absolute', left: 120, right: 120, top: ROW_Y + r * ROW_H - 26, height: ROW_H - 18, borderRadius: 18, opacity: show }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: 18, background: isA ? C.accentSoft : 'transparent', boxShadow: isA ? `inset 0 0 0 1.5px rgba(255,90,31,${0.5 * highlight})` : undefined, opacity: highlight }} />
            <div style={{ position: 'absolute', left: 40, top: 26 }}>
              <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 34, letterSpacing: '-0.02em', color: isA ? C.accent : C.text }}>{row.name}</div>
              <div style={{ marginTop: 6, fontFamily: SANS, fontSize: 20, color: C.muted }}>{row.sub}</div>
            </div>
            <div style={{ position: 'absolute', left: GX - 120, top: 36, display: 'flex', gap: 30 }}>
              {setIds.map((s, g) => (
                <div key={s} style={{ display: 'flex', gap: 12 }}>
                  {data.sets[s][row.id].map((ok, k) => {
                    const i = g * 3 + k
                    const q = isA ? pop(sec, at + 0.05 + i * 0.045, fps, { damping: 11, stiffness: 230, mass: 0.6 }) : ramp(sec, at + 0.15 + i * 0.05, 0.3)
                    return (
                      <div
                        key={k}
                        style={{
                          width: SQ,
                          height: SQ,
                          borderRadius: 12,
                          background: ok ? (isA ? C.accent : C.text) : C.badSoft,
                          boxShadow: ok ? undefined : `inset 0 0 0 2px ${C.bad}`,
                          opacity: Math.min(1, q * 1.5),
                          transform: `scale(${0.4 + 0.6 * q})`,
                        }}
                      />
                    )
                  })}
                </div>
              ))}
            </div>
            <div
              style={{
                position: 'absolute',
                left: 1352,
                top: isA ? 12 : 24,
                fontFamily: SANS,
                fontWeight: 600,
                fontSize: isA ? 88 : 64,
                letterSpacing: '-0.05em',
                color: isA ? C.accent : n === 0 ? C.bad : C.text,
                transform: `scale(${isA ? 0.6 + 0.4 * land : 1})`,
                transformOrigin: '0% 60%',
                whiteSpace: 'nowrap',
              }}
            >
              {n} <span style={{ fontSize: isA ? 50 : 36, color: C.muted, fontWeight: 500 }}>of 9</span>
            </div>
            {isA && ping > 0 && ping < 1 && (
              <div style={{ position: 'absolute', left: 1400, top: 66, width: 0, height: 0 }}>
                <div style={{ position: 'absolute', left: -ping * 180, top: -ping * 180, width: ping * 360, height: ping * 360, borderRadius: '50%', border: `3px solid ${C.accent}`, opacity: 1 - ping }} />
              </div>
            )}
            <div style={{ position: 'absolute', right: 30, top: 48, fontFamily: SANS, fontSize: 24, color: C.muted, opacity: ramp(sec, timesAt + r * 0.12, 0.5), whiteSpace: 'nowrap' }}>
              {Math.round(data.conditions[row.id].median_wall_seconds)} s
            </div>
          </div>
        )
      })}
      <div style={{ position: 'absolute', right: 150, top: ROW_Y - 62, fontFamily: SANS, fontSize: 17, color: C.faint, opacity: ramp(sec, timesAt, 0.5), textAlign: 'right' }}>median per pair</div>

      {/* The sample repo, smaller. */}
      <div style={{ position: 'absolute', left: 160, right: 160, top: 812, display: 'flex', alignItems: 'center', gap: 34, opacity: ramp(sec, sampleAt, 0.5), transform: `translateY(${(1 - ramp(sec, sampleAt, 0.5)) * 16}px)` }}>
        <div style={{ fontFamily: SANS, fontSize: 24, color: C.text, fontWeight: 600, whiteSpace: 'nowrap' }}>Sample repo, six kinds of change</div>
        <div style={{ fontFamily: SANS, fontSize: 22, color: C.muted, whiteSpace: 'nowrap' }}>
          worktrees <span style={{ color: C.bad, fontWeight: 600 }}>0 of 18</span> · broadcast <span style={{ color: C.text, fontWeight: 600 }}>3 of 18</span> · Airspace{' '}
          <span style={{ color: C.accent, fontWeight: 600 }}>17 of 18</span>
        </div>
        <div style={{ display: 'flex', gap: 5 }}>
          {Array.from({ length: 18 }, (_, k) => {
            const q = pop(sec, word('seventeen', sampleAt) - 0.1 + k * 0.03, fps, { damping: 12, stiffness: 220, mass: 0.6 })
            return <div key={k} style={{ width: 20, height: 20, borderRadius: 5, background: k < 17 ? C.accent : C.surface2, boxShadow: k < 17 ? undefined : `inset 0 0 0 1.5px ${C.lineStrong}`, transform: `scale(${0.3 + 0.7 * q})`, opacity: q }} />
          })}
        </div>
      </div>
      {void ease}
    </AbsoluteFill>
  )
}
