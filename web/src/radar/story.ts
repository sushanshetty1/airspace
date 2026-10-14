import { useEffect, useState } from 'react'
import type { AgentKey } from './graph'

export type Verdict = 'FILED' | 'CLEARED' | 'CONTRACT' | 'HOLD' | 'BRIEFED'

export type LogEntry = {
  step: number
  time: string
  verdict: Verdict
  agent: AgentKey
  /** What happened, as a sentence after the agent's name. Code in `code`. */
  text: string
  code: string
}

// One run, start to finish. Step n shows everything up to and including entry n.
export const log: LogEntry[] = [
  { step: 1, time: '10:42:03', verdict: 'FILED', agent: 'a', text: 'filed a plan for', code: 'slugify' },
  { step: 2, time: '10:42:05', verdict: 'FILED', agent: 'b', text: 'filed a plan for', code: 'render_post' },
  { step: 3, time: '10:42:19', verdict: 'CLEARED', agent: 'a', text: 'was cleared to edit', code: 'utils/text.py' },
  { step: 4, time: '10:42:20', verdict: 'CONTRACT', agent: 'a', text: 'changed the signature of', code: 'slugify' },
  { step: 5, time: '10:42:31', verdict: 'HOLD', agent: 'b', text: 'was held editing', code: 'blog/views.py' },
  { step: 6, time: '10:42:31', verdict: 'BRIEFED', agent: 'b', text: 'got the new signature of', code: 'slugify' },
  { step: 7, time: '10:42:44', verdict: 'CLEARED', agent: 'b', text: 'was cleared to edit', code: 'blog/views.py' },
]

export const FINAL_STEP = 7

/** The status each agent's flight strip shows at a given step. */
export function statusOf(agent: AgentKey, step: number): Verdict | null {
  if (agent === 'a') {
    if (step >= 4) return 'CONTRACT'
    if (step >= 3) return 'CLEARED'
    if (step >= 1) return 'FILED'
    return null
  }
  if (step >= 7) return 'CLEARED'
  if (step >= 6) return 'BRIEFED'
  if (step >= 5) return 'HOLD'
  if (step >= 2) return 'FILED'
  return null
}

// How long each step stays on screen before the next one, in ms. Index = step.
const durations = [1000, 1700, 1600, 1300, 1500, 2600, 1900, 3800]

/** Plays the run in a loop while `playing`. Reduced motion shows the end state. */
export function useStory(playing: boolean, reduced: boolean): number {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (reduced || !playing) return
    const id = window.setTimeout(() => setStep((s) => (s >= FINAL_STEP ? 0 : s + 1)), durations[step])
    return () => window.clearTimeout(id)
  }, [step, playing, reduced])

  return reduced ? FINAL_STEP : step
}
