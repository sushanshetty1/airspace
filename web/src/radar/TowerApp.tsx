import { Pause, Play } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { LogoMark, Sign, signLabel } from '../ui'
import { agents, type AgentKey } from './graph'
import { Scope } from './Scope'
import { log, statusOf } from './story'

const ease = [0.22, 1, 0.36, 1] as const

function AgentRow({ agent, step }: { agent: AgentKey; step: number }) {
  const c = agents[agent]
  const status = statusOf(agent, step)
  return (
    <div className={`flex items-center gap-3 rounded-[8px] px-2.5 py-2 transition-colors duration-500 ${status === 'HOLD' ? 'bg-accent-soft' : ''}`}>
      <span className="grid size-8 shrink-0 place-items-center rounded-[7px] text-[13px] font-bold text-ink" style={{ background: c.color }}>
        {agent.toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[13px] font-medium" style={{ color: c.color }}>
          {c.id}
        </p>
        <p className="truncate text-[13px] text-muted">{c.task}</p>
      </div>
      <AnimatePresence mode="wait">
        {status && (
          <motion.span key={status} initial={{ opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.25, ease }}>
            <Sign kind={status}>{signLabel[status]}</Sign>
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}

function Activity({ step }: { step: number }) {
  const rows = log.filter((r) => r.step <= step).slice().reverse()
  return (
    <ol className="space-y-0.5" aria-live="polite">
      <AnimatePresence initial={false}>
        {rows.map((r) => {
          const c = agents[r.agent]
          return (
            <motion.li key={r.step} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.4, ease }} className="overflow-hidden">
              <div className="grid grid-cols-[52px_minmax(0,1fr)] gap-2 px-2.5 py-1.5 text-[13px] leading-snug">
                <span className="pt-px font-mono text-[11.5px] text-faint">{r.time.slice(3)}</span>
                <p className="text-muted">
                  <span className="font-mono" style={{ color: c.color }}>
                    {c.id}
                  </span>{' '}
                  <span className={r.verdict === 'HOLD' ? 'font-semibold text-accent' : r.verdict === 'CLEARED' ? 'text-ok' : ''}>{r.text}</span>{' '}
                  <span className="font-mono text-[12.5px] text-text">{r.code}</span>
                </p>
              </div>
            </motion.li>
          )
        })}
      </AnimatePresence>
    </ol>
  )
}

/** The Tower app as it looks during a run: agents and activity on the left, the airspaces on the right. */
export function TowerApp({ step, paused, onTogglePause, showControls }: { step: number; paused: boolean; onTogglePause: () => void; showControls: boolean }) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-line bg-surface shadow-[0_30px_80px_-30px_rgb(0_0_0/0.5)]">
      <div className="flex h-11 items-center justify-between gap-4 border-b border-line px-4">
        <div className="flex min-w-0 items-center gap-2.5 text-[13.5px]">
          <LogoMark className="h-[13px] w-auto text-text" />
          <span className="font-semibold text-text">Tower</span>
          <span className="text-faint">/</span>
          <span className="truncate text-muted">blog-api</span>
        </div>
        {showControls && (
          <button
            type="button"
            onClick={onTogglePause}
            aria-label={paused ? 'Play the run' : 'Pause the run'}
            className="grid size-7 place-items-center rounded-[6px] text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            {paused ? <Play size={13} weight="fill" /> : <Pause size={13} weight="fill" />}
          </button>
        )}
      </div>
      <div className="grid lg:grid-cols-[290px_minmax(0,1fr)]">
        <aside className="order-2 border-t border-line p-3 lg:order-1 lg:border-t-0 lg:border-r">
          <p className="px-2.5 pt-1 pb-2 text-[12.5px] font-semibold text-muted">Agents</p>
          <div className="space-y-1">
            <AgentRow agent="a" step={step} />
            <AgentRow agent="b" step={step} />
          </div>
          <p className="px-2.5 pt-6 pb-2 text-[12.5px] font-semibold text-muted">Activity</p>
          <div className="lg:min-h-[250px]">
            {step === 0 ? <p className="px-2.5 py-1.5 text-[13px] text-faint">Waiting for a flight plan.</p> : <Activity step={step} />}
          </div>
        </aside>
        <div className="order-1 bg-bg/50 px-3 py-6 sm:px-8 sm:py-10 lg:order-2">
          <Scope step={step} />
        </div>
      </div>
    </div>
  )
}
