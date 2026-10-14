import { PauseCircle, PlayCircle } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { Sign, signLabel } from '../ui'
import { clock, type AgentState, type AirEvent, type TowerApi } from './api'
import { fallbackLook, type AgentLook } from './layout'

const ease = [0.22, 1, 0.36, 1] as const

export function AgentName({ id, look, className = '' }: { id: string; look?: AgentLook; className?: string }) {
  return (
    <span className={`font-mono ${className}`} style={{ color: (look ?? fallbackLook).color }}>
      {id}
    </span>
  )
}

export function AgentStatus({ agent }: { agent: AgentState }) {
  if (agent.held) return <Sign kind="HOLD">{signLabel.HOLD}</Sign>
  if (agent.paused) return <Sign kind="BRIEFED">Paused</Sign>
  if (agent.status === 'holding') return <Sign kind="BRIEFED">Holding</Sign>
  if (agent.status === 'landed') return <Sign kind="CLEARED">Landed</Sign>
  return <Sign kind="FILED">Flying</Sign>
}

type Pending = { agent: string; error: string | null; busy: boolean }

function AgentRow({ agent, look, api, onDone }: { agent: AgentState; look: AgentLook; api: TowerApi; onDone: () => void }) {
  const [pending, setPending] = useState<Pending | null>(null)
  const busy = pending?.busy ?? false
  const verb = agent.paused ? 'Resume' : 'Pause'

  const toggle = async () => {
    setPending({ agent: agent.id, busy: true, error: null })
    try {
      await (agent.paused ? api.resume(agent.id) : api.pause(agent.id))
      setPending(null)
      onDone()
    } catch {
      setPending({ agent: agent.id, busy: false, error: `Could not ${verb.toLowerCase()} ${agent.id}. Try again.` })
    }
  }

  const claims = agent.claims.length
  return (
    <li className={`rounded-[8px] px-2.5 py-2 transition-colors duration-500 ${agent.held ? 'bg-accent-soft' : ''}`}>
      <div className="flex items-center gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-[7px] text-[13px] font-bold text-ink" style={{ background: agent.paused ? 'var(--line-strong)' : look.color }} aria-hidden="true">
          {look.letter}
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center justify-between gap-2">
            <AgentName id={agent.id} look={look} className="truncate text-[13px] font-medium" />
            <AgentStatus agent={agent} />
          </p>
          <p className="mt-0.5 flex items-center justify-between gap-2 text-[13px] text-muted">
            <span className="truncate">{claims === 1 ? '1 claim' : `${claims} claims`}</span>
            <button
              type="button"
              onClick={toggle}
              disabled={busy}
              aria-label={`${verb} ${agent.id}`}
              className="-mr-1 inline-flex h-6 items-center gap-1 rounded-[6px] px-1.5 text-[12.5px] font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:opacity-50"
            >
              {agent.paused ? <PlayCircle size={14} weight="bold" /> : <PauseCircle size={14} weight="bold" />}
              {busy ? (agent.paused ? 'Resuming' : 'Pausing') : verb}
            </button>
          </p>
        </div>
      </div>
      {pending?.error && (
        <p className="mt-1.5 pl-11 text-[12.5px] text-bad" role="alert">
          {pending.error}
        </p>
      )}
    </li>
  )
}

function Activity({ events, looks }: { events: AirEvent[]; looks: Record<string, AgentLook> }) {
  const rows = events.slice().reverse().slice(0, 120)
  if (!rows.length) return <p className="px-2.5 py-1.5 text-[13px] text-faint">Nothing has happened yet.</p>
  return (
    <ol className="space-y-0.5" aria-live="polite">
      <AnimatePresence initial={false}>
        {rows.map((e) => (
          <motion.li key={e.id} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.4, ease }} className="overflow-hidden">
            <div className="grid grid-cols-[60px_minmax(0,1fr)] gap-2 px-2.5 py-1.5 text-[13px] leading-snug">
              <span className="pt-px font-mono text-[11.5px] text-faint">{clock(e.at)}</span>
              <p className="text-muted [overflow-wrap:anywhere]">
                <AgentName id={e.agent} look={looks[e.agent]} />{' '}
                <span className={e.kind === 'hold' ? 'font-semibold text-accent' : e.kind === 'cleared' || e.kind === 'resolved' ? 'text-ok' : ''}>{e.text}</span>{' '}
                {e.code === 'Tower' ? <span className="text-text">Tower</span> : <span className="font-mono text-[12.5px] text-text">{e.code}</span>}
              </p>
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  )
}

export function Sidebar({ agents, events, looks, api, onChanged }: { agents: AgentState[]; events: AirEvent[]; looks: Record<string, AgentLook>; api: TowerApi; onChanged: () => void }) {
  return (
    <div className="p-3">
      <h2 className="flex items-baseline justify-between px-2.5 pt-1 pb-2 text-[12.5px] font-semibold text-muted">
        Agents <span className="font-normal text-faint">{agents.length}</span>
      </h2>
      <ul className="space-y-1">
        {agents.map((a) => (
          <AgentRow key={a.id} agent={a} look={looks[a.id] ?? fallbackLook} api={api} onDone={onChanged} />
        ))}
      </ul>
      <h2 className="px-2.5 pt-6 pb-2 text-[12.5px] font-semibold text-muted">Activity</h2>
      <Activity events={events} looks={looks} />
    </div>
  )
}
