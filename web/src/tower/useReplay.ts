import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, type CollisionDetail, type TowerApi } from './api'
import { frameDelay, type ReplayDoc } from './replay'
import type { Live, Phase } from './useLive'

export type Player = {
  /** The frame on screen. */
  index: number
  count: number
  playing: boolean
  /** Seconds of the recorded run up to the frame on screen, and in all. */
  elapsed: number
  total: number
  toggle: () => void
  seek: (index: number) => void
}

const off = () => Promise.reject(new ApiError(0, 'Tower controls are off while it plays a recording.'))

/**
 * Plays a recorded run. Gives Tower the same Live shape it gets from the server,
 * taken from the frame on screen, plus a player for the timeline.
 */
export function useReplay(load: () => Promise<ReplayDoc>): { live: Live; player: Player; api: TowerApi } {
  const [doc, setDoc] = useState<ReplayDoc | null>(null)
  const [phase, setPhase] = useState<Phase>('loading')
  const [attempt, setAttempt] = useState(0)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    let alive = true
    load()
      .then((d) => {
        if (!alive) return
        setDoc(d)
        setIndex(0)
        setPlaying(d.frames.length > 1)
        setPhase('ready')
      })
      .catch(() => alive && setPhase('error'))
    return () => {
      alive = false
    }
  }, [load, attempt])

  const count = doc?.frames.length ?? 0
  // Playing stops by itself on the last frame.
  const running = playing && index < count - 1

  // Advance one frame at a time, waiting the run's own gap (kept short) between frames.
  useEffect(() => {
    if (!running || !doc) return
    const t = window.setTimeout(() => setIndex((i) => Math.min(i + 1, count - 1)), frameDelay(doc.frames, index))
    return () => window.clearTimeout(t)
  }, [running, index, doc, count])

  const toggle = useCallback(() => {
    if (running) return setPlaying(false)
    // From the end, play from the start again.
    if (index >= count - 1) setIndex(0)
    setPlaying(count > 1)
  }, [running, index, count])

  const seek = useCallback(
    (i: number) => {
      setIndex(Math.max(0, Math.min(count - 1, Math.round(i))))
    },
    [count],
  )

  const frame = doc?.frames[index]
  const events = useMemo(() => (doc && frame ? doc.events.filter((e) => e.at <= frame.at) : []), [doc, frame])

  // Answers from the frame on screen, so the collision panel shows each collision as it stood then.
  const api: TowerApi = useMemo(
    () => ({
      state: async () => (frame ? frame.state : Promise.reject(new ApiError(0, 'No frame.'))),
      radar: async () => (frame ? frame.radar : Promise.reject(new ApiError(0, 'No frame.'))),
      events: async (since) => events.filter((e) => e.at > since),
      collision: async (id) => {
        const detail = doc?.collisions[id]
        if (!detail) return null
        // The recording keeps each collision as it ended.
        const then = frame?.state.collisions.find((c) => c.id === id)
        return { ...detail, resolution: then?.resolution ?? detail.resolution } satisfies CollisionDetail
      },
      pause: off,
      resume: off,
      message: off,
      release: off,
      stream: () => () => {},
    }),
    [doc, frame, events],
  )

  const retry = useCallback(() => {
    setPhase('loading')
    setAttempt((a) => a + 1)
  }, [])

  const first = doc?.frames[0]?.at ?? 0
  const last = doc?.frames[count - 1]?.at ?? 0
  const live: Live = {
    phase,
    conn: 'live',
    state: frame?.state ?? null,
    radar: frame?.radar ?? null,
    events,
    tick: index + 1,
    refresh: () => {},
    retry,
  }
  return {
    live,
    player: { index, count, playing: running, elapsed: frame ? frame.at - first : 0, total: last - first, toggle, seek },
    api,
  }
}
