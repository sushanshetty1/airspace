// Captions: the voice's own lines, timed by its alignment, in the brand sans, two lines at most, in the band under
// the slab.

import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import { BAND, C, SANS } from '../brand'
import timing from '../timing.json'

type Cue = { text: string; start: number; end: number }
type Word = { w: string; start: number; end: number }
const T = timing as unknown as { order: string[]; scenes: Record<string, { chunks: Cue[]; words: Word[] }> }

export function cues(): Cue[] {
  const out: Cue[] = []
  for (const id of T.order) for (const c of T.scenes[id].chunks) out.push(c)
  // Each line holds until the next begins (the narration has no gaps to show an empty band in).
  return out.map((c, i) => {
    const next = out[i + 1]
    const hold = next && next.start - c.end < 1.2 ? next.start - 0.05 : c.end + 0.5
    return { ...c, start: c.start - 0.08, end: hold }
  })
}

const LIST = cues()

export function Captions() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const t = frame / fps
  const cue = LIST.find((c) => t >= c.start && t < c.end)
  if (!cue) return null
  const age = t - cue.start
  const left = cue.end - t
  const inP = interpolate(age, [0, 0.16], [0, 1], { extrapolateRight: 'clamp' })
  const outP = interpolate(left, [0, 0.1], [0, 1], { extrapolateRight: 'clamp' })
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, top: BAND.top, bottom: 1080 - BAND.bottom, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div
        style={{
          maxWidth: 1480,
          textAlign: 'center',
          fontFamily: SANS,
          fontWeight: 500,
          fontSize: 31,
          lineHeight: 1.3,
          letterSpacing: '-0.01em',
          color: C.text,
          opacity: Math.min(inP, outP),
          transform: `translateY(${(1 - inP) * 6}px)`,
          textWrap: 'balance',
        }}
      >
        {/* Names such as agent-a never break at their hyphen. */}
        {cue.text.split(/(\S*-\S*)/).map((part, i) => (i % 2 ? <span key={i} style={{ whiteSpace: 'nowrap' }}>{part}</span> : part))}
      </div>
    </div>
  )
}
