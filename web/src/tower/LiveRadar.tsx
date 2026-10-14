import { useMemo, useSyncExternalStore } from 'react'
import { ScopeView } from '../radar/Scope'
import type { RadarData, StateData } from './api'
import { shortName } from './api'
import { layoutRadar, type AgentLook } from './layout'

// Matches the breakpoint where Scope hides cone labels (index.css, .scope-minor).
const PHONE = '(max-width: 639px)'

function usePhone() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(PHONE)
      mq.addEventListener('change', cb)
      return () => mq.removeEventListener('change', cb)
    },
    () => window.matchMedia(PHONE).matches,
  )
}

function describe(radar: RadarData) {
  const parts = radar.agents.map((a) => `${a.id} ${a.center ? `is working on ${shortName(a.center, radar.symbols)}` : 'has no plan yet'}`)
  const c = radar.collision
  if (c) {
    const state = c.resolution === 'held' ? 'is held' : c.resolution === 'released' ? 'had its hold released' : 'was cleared'
    parts.push(`${c.held_agent} ${state} at ${shortName(c.symbol, radar.symbols)}, which ${c.owner_agent} is changing`)
  }
  return `Airspaces. ${parts.join('. ')}.`
}

/** The live airspaces. Clicking the orange lens opens the collision. */
export function LiveRadar({ radar, state, looks, onOpenCollision }: { radar: RadarData; state: StateData | null; looks: Record<string, AgentLook>; onOpenCollision: (id: string) => void }) {
  const compact = usePhone()
  const paused = useMemo(() => new Set((state?.agents ?? []).filter((a) => a.paused).map((a) => a.id)), [state])
  const { model } = useMemo(() => layoutRadar(radar, looks, paused, { onLens: onOpenCollision, compact }), [radar, looks, paused, onOpenCollision, compact])
  // Never drawn larger than 0.9 px per unit, so labels stay at app size, not hero size.
  return <ScopeView model={model} label={describe(radar)} className="mx-auto max-h-[calc(100dvh-220px)] min-h-[180px]" style={{ maxWidth: Math.round(model.view.w * 0.9) }} />
}
