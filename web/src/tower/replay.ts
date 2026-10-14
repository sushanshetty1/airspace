// Replays: a recorded run that Tower plays back with the same views it uses live.
// The server writes them with `python -m airspace.replay watch` and serves them at /api/replay.

import { ApiError, type AirEvent, type CollisionDetail, type RadarData, type StateData } from './api'

export type ReplayFrame = { at: number; state: StateData; radar: RadarData }

export type ReplayDoc = {
  version: number
  recorded_at: number
  events: AirEvent[]
  /** One per moment something happened, oldest first. */
  frames: ReplayFrame[]
  collisions: Record<string, CollisionDetail>
}

async function getJson<T>(path: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(path)
  } catch {
    throw new ApiError(0, 'The Airspace server did not answer.')
  }
  const data = (await res.json().catch(() => null)) as { error?: string } | null
  if (!res.ok) throw new ApiError(res.status, data?.error || `The server answered ${res.status}.`)
  return data as T
}

export async function fetchReplay(): Promise<ReplayDoc> {
  const doc = await getJson<ReplayDoc>('/api/replay')
  if (!doc || !Array.isArray(doc.frames) || !Array.isArray(doc.events)) throw new ApiError(0, 'The replay file is not one Tower can read.')
  return { ...doc, collisions: doc.collisions ?? {} }
}

/** "replay" when the server has a recording and no agent is flying. Older servers have no /api/mode: live. */
export async function fetchMode(): Promise<'live' | 'replay'> {
  const { mode } = await getJson<{ mode: string }>('/api/mode')
  return mode === 'replay' ? 'replay' : 'live'
}

/** The frame on screen for at most this long while playing, and at least this long, in seconds. */
const MAX_GAP = 2.4
const MIN_GAP = 0.45

/** How long frame i stays up while playing: the real gap to the next frame, kept between the limits above. */
export function frameDelay(frames: ReplayFrame[], i: number) {
  if (i >= frames.length - 1) return 0
  return Math.min(MAX_GAP, Math.max(MIN_GAP, frames[i + 1].at - frames[i].at)) * 1000
}

/** 75 seconds as 1:15. */
export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
