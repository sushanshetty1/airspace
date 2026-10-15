// The end card: the mark closes its two airspaces and the lens turns orange; the links are on screen, not read.

import { AbsoluteFill, Img, interpolate, staticFile } from 'remotion'
import { C, SANS } from '../brand'
import { LogoMark, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'

export function Close() {
  const { sec, fps } = useSec()
  const { inEnd } = useSceneTime()
  const t0 = inEnd - 0.55
  const close = pop(sec, t0, fps, { damping: 16, stiffness: 90, mass: 1 })
  const lens = interpolate(sec, [t0 + 0.55, t0 + 0.85], [0, 1], clamp)
  const word = ramp(sec, t0 + 0.5, 0.6)
  const tag = ramp(sec, t0 + 0.8, 0.6)
  const links = ramp(sec, t0 + 1.5, 0.6)
  const built = ramp(sec, t0 + 2.0, 0.6)
  const track = ramp(sec, t0 + 2.4, 0.6)

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'absolute', top: 170, left: 0, right: 0, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 34 }}>
          <LogoMark size={118} p={interpolate(close, [0, 1], [3.2, 1])} lens={lens} />
          <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: 132, letterSpacing: '-0.045em', color: C.text, opacity: word, transform: `translateX(${(1 - word) * -24}px)` }}>Airspace</span>
        </div>
        <div style={{ marginTop: 26, fontFamily: SANS, fontSize: 40, fontWeight: 500, color: C.muted, letterSpacing: '-0.02em', opacity: tag, transform: `translateY(${(1 - tag) * 12}px)` }}>
          Air-traffic control for coding agents.
        </div>

        <div style={{ marginTop: 70, display: 'flex', gap: 22, opacity: links, transform: `translateY(${(1 - links) * 14}px)` }}>
          {['airspace.sushans.dev', 'github.com/sushanshetty1/airspace'].map((l, i) => (
            <div
              key={l}
              style={{
                fontFamily: SANS,
                fontSize: 30,
                fontWeight: 600,
                color: i === 0 ? C.accentInk : C.text,
                background: i === 0 ? C.accent : 'transparent',
                boxShadow: i === 0 ? undefined : `inset 0 0 0 1.5px ${C.lineStrong}`,
                padding: '16px 28px',
                borderRadius: 12,
              }}
            >
              {l}
            </div>
          ))}
        </div>

        <div style={{ marginTop: 64, display: 'flex', alignItems: 'center', gap: 14, opacity: built }}>
          <Img src={staticFile('logos/falkordb.svg')} style={{ width: 40, height: 40, borderRadius: 8 }} />
          <span style={{ fontFamily: SANS, fontSize: 28, color: C.text }}>
            Built on <span style={{ fontWeight: 600 }}>FalkorDB</span>
          </span>
        </div>
        <div style={{ marginTop: 26, fontFamily: SANS, fontSize: 22, color: C.muted, opacity: track, textAlign: 'center', lineHeight: 1.5 }}>
          FalkorDB Hackathon 2026
          <br />
          Track 01, Agents That Act on Connected Data · Track 02, Agent Memory and Coordination
        </div>
      </div>
    </AbsoluteFill>
  )
}
