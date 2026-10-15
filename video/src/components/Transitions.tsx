// Three transition families, all in Airspace's own marks:
//   sweep  the radar beam turns once around the frame and the next scene is painted in behind it;
//   lens   two airspaces close in over the outgoing scene, their overlap turns orange (the logo), and the lens
//          opens out to become the next scene, with the section's name under it;
//   path   a flight path is drawn across the frame and the scenes travel along it, one banking out, one in.

import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, H, SANS, W, ease, easeIn, easeInOut } from '../brand'
import { TRANSITION, type Placed } from '../timeline'
import { clamp } from './ui'

const CX = W / 2
const CY = H / 2 - 20

function SweepBeam({ deg, fade }: { deg: number; fade: number }) {
  const rad = ((deg - 90) * Math.PI) / 180
  const L = 1400
  return (
    <AbsoluteFill style={{ opacity: fade, pointerEvents: 'none' }}>
      {/* The trail behind the beam: a thin wedge of cyan light. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `conic-gradient(from ${deg - 34}deg at ${CX}px ${CY}px, transparent 0deg, rgba(69,196,230,0.0) 2deg, rgba(69,196,230,0.16) 33deg, rgba(69,196,230,0.32) 34deg, transparent 34.2deg)`,
        }}
      />
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
        <defs>
          <linearGradient id="beam" x1={CX} y1={CY} x2={CX + Math.cos(rad) * L} y2={CY + Math.sin(rad) * L} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#e9fbff" stopOpacity={0.95} />
            <stop offset="1" stopColor={C.a} stopOpacity={0.5} />
          </linearGradient>
        </defs>
        <line x1={CX} y1={CY} x2={CX + Math.cos(rad) * L} y2={CY + Math.sin(rad) * L} stroke={C.a} strokeOpacity={0.35} strokeWidth={10} style={{ filter: 'blur(6px)' }} />
        <line x1={CX} y1={CY} x2={CX + Math.cos(rad) * L} y2={CY + Math.sin(rad) * L} stroke="url(#beam)" strokeWidth={2.5} />
        <circle cx={CX} cy={CY} r={7} fill="#e9fbff" />
        <circle cx={CX} cy={CY} r={18} fill="none" stroke={C.a} strokeOpacity={0.5} strokeWidth={1.5} />
      </svg>
    </AbsoluteFill>
  )
}

/** The lens transition's clock, in seconds from its start. */
const LENS = { close: [0, 0.5], fill: [0.32, 0.6], label: [0.28, 0.5], open: [0.72, 1.42], labelOut: [0.78, 1.0] } as const
const R0 = 210
const OFF = 118

function lensGeometry(sec: number, fps: number) {
  const close = spring({ frame: sec * fps, fps, config: { damping: 18, stiffness: 120, mass: 0.8 } })
  const open = interpolate(sec, LENS.open as unknown as number[], [0, 1], { ...clamp, easing: easeInOut })
  const k = 1 + open * 9.5 // the lens grows until it covers the frame
  const off = (OFF + (1 - close) * 760) * k
  const r = R0 * k
  return { close, open, off, r }
}

function LensOverlay({ sec, fps, label }: { sec: number; fps: number; label: string }) {
  const { close, open, off, r } = lensGeometry(sec, fps)
  const fill = interpolate(sec, LENS.fill as unknown as number[], [0, 1], { ...clamp, easing: ease })
  const labelIn = interpolate(sec, LENS.label as unknown as number[], [0, 1], { ...clamp, easing: ease })
  const labelOut = interpolate(sec, LENS.labelOut as unknown as number[], [0, 1], { ...clamp, easing: easeIn })
  const ringFade = 1 - interpolate(open, [0.25, 0.7], [0, 1], clamp)
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
        <defs>
          <clipPath id="lensA">
            <circle cx={CX - off} cy={CY} r={r} />
          </clipPath>
          <clipPath id="lensB">
            <circle cx={CX + off} cy={CY} r={r} />
          </clipPath>
        </defs>
        {/* The lens fills orange while the airspaces meet, then clears as it opens: only its edge stays, a thin
            orange band around the next scene, so the frame reads straight through it. */}
        <circle cx={CX + off} cy={CY} r={r} fill={C.accent} opacity={fill * (1 - interpolate(open, [0, 0.18], [0, 1], clamp))} clipPath="url(#lensA)" />
        <g opacity={open > 0 ? 1 - interpolate(open, [0.55, 0.95], [0, 1], clamp) : 0}>
          <circle cx={CX + off} cy={CY} r={r} fill="none" stroke={C.accent} strokeWidth={7} clipPath="url(#lensA)" />
          <circle cx={CX - off} cy={CY} r={r} fill="none" stroke={C.accent} strokeWidth={7} clipPath="url(#lensB)" />
        </g>
        <circle cx={CX - off} cy={CY} r={r - 4} fill="none" stroke={C.a} strokeWidth={5} opacity={ringFade * Math.min(1, close * 1.4)} />
        <circle cx={CX + off} cy={CY} r={r - 4} fill="none" stroke={C.b} strokeWidth={5} opacity={ringFade * Math.min(1, close * 1.4)} />
      </svg>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: CY + R0 + 34,
          textAlign: 'center',
          fontFamily: SANS,
          fontWeight: 600,
          fontSize: 58,
          letterSpacing: '-0.035em',
          color: C.text,
          opacity: labelIn * (1 - labelOut),
          transform: `translateY(${(1 - labelIn) * 18 - labelOut * 10}px)`,
        }}
      >
        {label}
      </div>
    </AbsoluteFill>
  )
}

/** The scene revealed through the opening lens: the intersection of the two circles, as two nested clips. */
function LensReveal({ sec, fps, children }: { sec: number; fps: number; children: ReactNode }) {
  const { open, off, r } = lensGeometry(sec, fps)
  if (open <= 0) return null
  if (open >= 1) return <>{children}</>
  return (
    <AbsoluteFill style={{ clipPath: `circle(${r}px at ${CX - off}px ${CY}px)` }}>
      <AbsoluteFill style={{ clipPath: `circle(${r}px at ${CX + off}px ${CY}px)` }}>{children}</AbsoluteFill>
    </AbsoluteFill>
  )
}

function FlightPath({ p, fade }: { p: number; fade: number }) {
  // A gentle climb from the lower left to the upper right, drawn as a dashed track with the aircraft on it.
  const x0 = -80
  const y0 = H * 0.82
  const x3 = W + 80
  const y3 = H * 0.16
  const c1 = { x: W * 0.32, y: H * 0.86 }
  const c2 = { x: W * 0.62, y: H * 0.12 }
  const bez = (t: number) => {
    const u = 1 - t
    return {
      x: u * u * u * x0 + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * x3,
      y: u * u * u * y0 + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * y3,
    }
  }
  const d = `M${x0} ${y0} C${c1.x} ${c1.y} ${c2.x} ${c2.y} ${x3} ${y3}`
  const len = 2400
  const at = bez(Math.min(1, p))
  return (
    <svg width={W} height={H} style={{ position: 'absolute', inset: 0, opacity: fade, pointerEvents: 'none', overflow: 'visible' }}>
      <path d={d} fill="none" stroke={C.a} strokeOpacity={0.25} strokeWidth={10} strokeDasharray={len} strokeDashoffset={len * (1 - p)} style={{ filter: 'blur(5px)' }} />
      <path d={d} fill="none" stroke="#dff7ff" strokeWidth={2.5} strokeDasharray={`${len * p} ${len}`} />
      <path d={d} fill="none" stroke={C.bg} strokeWidth={3} strokeDasharray="10 14" strokeDashoffset={-p * 300} opacity={0.6} />
      <circle cx={at.x} cy={at.y} r={22} fill="none" stroke={C.a} strokeOpacity={0.45} strokeWidth={2} />
      <circle cx={at.x} cy={at.y} r={8} fill="#e9fbff" />
    </svg>
  )
}

export function Transitioned({ scene, children }: { scene: Placed; children: ReactNode }) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const sec = frame / fps
  const into = scene.into
  const T = TRANSITION[into.kind].dur
  const out = scene.next?.into.kind
  const outT = out ? TRANSITION[out].dur : 0
  const gone = sec - (scene.dur - outT) // seconds since the next scene began coming in

  // Exit: what this scene does while the next one comes in over it.
  let exitStyle: CSSProperties = {}
  if (out === 'lens' && gone > 0) {
    const q = interpolate(gone, [0, 0.6], [0, 1], { ...clamp, easing: ease })
    exitStyle = { transform: `scale(${1 - q * 0.04})`, filter: `brightness(${1 - q * 0.62}) saturate(${1 - q * 0.4})` }
  }
  if (out === 'path' && gone > 0) {
    const q = interpolate(gone, [0, outT * 0.85], [0, 1], { ...clamp, easing: easeIn })
    exitStyle = { transform: `translate(${-q * 520}px, ${q * 120}px) rotate(${q * 2.5}deg) scale(${1 - q * 0.1})`, opacity: 1 - q }
  }
  if (out === 'sweep' && gone > 0) {
    const q = interpolate(gone, [0, outT], [0, 1], clamp)
    exitStyle = { filter: `brightness(${1 - q * 0.35})` }
  }

  let content: ReactNode = <AbsoluteFill style={{ ...exitStyle, transformOrigin: '50% 45%' }}>{children}</AbsoluteFill>
  let overlay: ReactNode = null
  if (into.kind === 'sweep' && sec < T + 0.2) {
    const deg = interpolate(sec, [0, T], [0, 360], { ...clamp, easing: easeInOut })
    const mask = `conic-gradient(from 0deg at ${CX}px ${CY}px, #000 0deg, #000 ${deg}deg, transparent ${Math.min(360, deg + 0.6)}deg)`
    content = <AbsoluteFill style={{ WebkitMaskImage: sec < T ? mask : undefined, maskImage: sec < T ? mask : undefined }}>{content}</AbsoluteFill>
    overlay = <SweepBeam deg={deg} fade={interpolate(sec, [T - 0.15, T + 0.15], [1, 0], clamp)} />
  }
  if (into.kind === 'lens' && sec < T + 0.1) {
    content = (
      <LensReveal sec={sec} fps={fps}>
        {content}
      </LensReveal>
    )
    overlay = <LensOverlay sec={sec} fps={fps} label={into.label} />
  }
  if (into.kind === 'path' && sec < T + 0.3) {
    const p = spring({ frame: (sec - 0.12) * fps, fps, config: { damping: 22, stiffness: 95, mass: 1 } })
    content = (
      <AbsoluteFill style={{ transform: `translate(${(1 - p) * 640}px, ${-(1 - p) * 150}px) rotate(${-(1 - p) * 2.5}deg) scale(${0.9 + 0.1 * p})`, opacity: Math.min(1, Math.max(0, (sec - 0.12) / 0.25)) }}>
        {content}
      </AbsoluteFill>
    )
    const draw = interpolate(sec, [0, T * 0.8], [0, 1], { ...clamp, easing: easeInOut })
    overlay = <FlightPath p={draw} fade={interpolate(sec, [T * 0.75, T + 0.25], [1, 0], clamp)} />
  }

  return (
    <AbsoluteFill>
      {content}
      {overlay}
    </AbsoluteFill>
  )
}
