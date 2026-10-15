// One take inside a scene, from `from` to `to` scene seconds. A clip that follows another flies in along the
// flight path (from the right, settling with a spring) while the one before banks away to the left.

import type { ComponentProps } from 'react'
import { AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { easeIn } from '../brand'
import { Footage, FootageFrame } from './Footage'

type Props = Omit<ComponentProps<typeof Footage>, 'from'> & {
  from: number
  to: number
  enter?: boolean
  exit?: boolean
  box?: { x: number; y: number; w: number }
}

export const CLIP_OUT = 0.55

function Inner({ from, to, enter, exit, box, ...rest }: Props) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const sec = frame / fps
  const len = to - from
  const p = enter ? spring({ frame, fps, config: { damping: 20, stiffness: 110, mass: 0.9 } }) : 1
  const q = exit ? interpolate(sec, [len - 0.05, len + CLIP_OUT], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: easeIn }) : 0
  return (
    <AbsoluteFill
      style={{
        transform: `translate(${(1 - p) * 220 - q * 260}px, ${(1 - p) * 26 - q * 18}px) scale(${(0.95 + 0.05 * p) * (1 - q * 0.06)})`,
        opacity: (enter ? Math.min(1, sec / 0.2) : 1) * (1 - q),
      }}
    >
      <FootageFrame box={box}>
        <Footage {...rest} />
      </FootageFrame>
    </AbsoluteFill>
  )
}

/** Warps, shots, rings and labels in a clip are in scene seconds, like everything else in the scene. */
export function Clip(props: Props) {
  const { fps } = useVideoConfig()
  const start = Math.round(props.from * fps)
  const dur = Math.round((props.to - props.from + (props.exit ? CLIP_OUT + 0.1 : 0)) * fps)
  const shift = props.from
  const warp = props.warp.map(([s, t]) => [s - shift, t] as [number, number])
  const shots = props.shots?.map((x) => ({ ...x, at: x.at - shift }))
  const rings = props.rings?.map((x) => ({ ...x, at: x.at - shift, until: x.until - shift }))
  const labels = props.labels?.map((x) => ({ ...x, at: x.at - shift, until: x.until - shift }))
  return (
    <Sequence from={start} durationInFrames={Math.max(1, dur)} layout="none">
      <Inner {...props} warp={warp} shots={shots} rings={rings} labels={labels} />
    </Sequence>
  )
}
