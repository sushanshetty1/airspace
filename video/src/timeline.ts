// The running order. The narration is one continuous track (scripts/voice.mjs); each scene is placed on it by its
// voice: it comes in `lead` seconds before its first line, through a transition that plays under the end of the
// previous line and the start of its own, so the picture never waits for the voice and the voice never waits for
// the picture.

import { createContext, useContext } from 'react'
import { FPS } from './brand'
import timing from './timing.json'

export type Into = { kind: 'none' } | { kind: 'sweep' } | { kind: 'path' } | { kind: 'lens'; label: string }

export type SceneDef = { id: string; into: Into }

export const SCENES: SceneDef[] = [
  { id: 'open', into: { kind: 'none' } },
  { id: 'idea', into: { kind: 'sweep' } },
  { id: 'tower', into: { kind: 'lens', label: 'Tower' } },
  { id: 'preflight', into: { kind: 'lens', label: 'Pre-flight' } },
  { id: 'memory', into: { kind: 'path' } },
  { id: 'playground', into: { kind: 'sweep' } },
  { id: 'workspaces', into: { kind: 'path' } },
  { id: 'numbers', into: { kind: 'lens', label: 'Results' } },
  { id: 'close', into: { kind: 'sweep' } },
]

/** How long each transition runs, and how far ahead of the new scene's first line it starts. */
export const TRANSITION: Record<Into['kind'], { dur: number; lead: number }> = {
  none: { dur: 0, lead: 0.7 },
  sweep: { dur: 1.0, lead: 0.45 },
  path: { dur: 0.95, lead: 0.4 },
  lens: { dur: 1.45, lead: 0.8 },
}

type Chunk = { text: string; start: number; end: number }
type Word = { w: string; start: number; end: number }
type VoiceScene = { start: number; end: number; chunks: Chunk[]; words: Word[] }
const T = timing as unknown as { total: number; scenes: Record<string, VoiceScene> }

export type Placed = SceneDef & { start: number; dur: number; voice: VoiceScene; next?: SceneDef }

export function placed(): { scenes: Placed[]; total: number } {
  const starts = SCENES.map((s, i) => (i === 0 ? 0 : T.scenes[s.id].start - TRANSITION[s.into.kind].lead))
  const total = T.total
  const scenes = SCENES.map((s, i) => {
    const end = i < SCENES.length - 1 ? starts[i + 1] + TRANSITION[SCENES[i + 1].into.kind].dur : total
    return { ...s, start: starts[i], dur: end - starts[i], voice: T.scenes[s.id], next: SCENES[i + 1] }
  })
  return { scenes, total }
}

export const toFrames = (sec: number) => Math.round(sec * FPS)

/** Inside a scene, in seconds from the scene's start: when line i starts and ends, and when a word is said. */
export type SceneTime = {
  c: (i: number) => number
  ce: (i: number) => number
  word: (w: string, after?: number) => number
  dur: number
  /** When this scene's transition in is over. */
  inEnd: number
  /** When the next scene's transition starts covering this one. */
  outStart: number
}

export function sceneTime(p: Placed): SceneTime {
  const ch = p.voice.chunks
  const outDur = p.next ? TRANSITION[p.next.into.kind].dur : 0
  return {
    c: (i) => ch[Math.min(i, ch.length - 1)].start - p.start,
    ce: (i) => ch[Math.min(i, ch.length - 1)].end - p.start,
    word: (w, after = 0) => {
      const hit = p.voice.words.find((x) => x.w.toLowerCase().startsWith(w.toLowerCase()) && x.start - p.start >= after)
      return hit ? hit.start - p.start : after
    },
    dur: p.dur,
    inEnd: TRANSITION[p.into.kind].dur,
    outStart: p.dur - outDur,
  }
}

export const SceneContext = createContext<SceneTime | null>(null)
export function useSceneTime(): SceneTime {
  const s = useContext(SceneContext)
  if (!s) throw new Error('no scene')
  return s
}
