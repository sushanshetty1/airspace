import { AnimatePresence, motion } from 'motion/react'
import { Sign } from '../ui'
import { agents, type AgentKey } from './graph'
import { log, statusOf } from './story'

const ease = [0.22, 1, 0.36, 1] as const

const claimLabel: Record<AgentKey, string> = { a: 'utils.text.slugify', b: 'blog.views.render_post' }

/** One flight strip per agent: callsign, task, what it claims, and its current clearance. */
function Strip({ agent, step }: { agent: AgentKey; step: number }) {
  const c = agents[agent]
  const status = statusOf(agent, step)
  const held = status === 'HOLD'
  return (
    <div className={`grid grid-cols-[96px_minmax(0,1fr)] border transition-colors duration-500 ${held ? 'border-accent' : 'border-line'}`}>
      <div className="flex items-center px-3 py-3 text-ink" style={{ background: c.color }}>
        <span className="font-label text-[12px] font-bold tracking-[0.05em] whitespace-nowrap">{c.id.toUpperCase()}</span>
      </div>
      <div className="flex min-w-0 items-center gap-3 bg-surface px-3.5 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-medium text-text">{c.task}</p>
          <p className="mt-0.5 truncate font-mono text-[11.5px] text-muted">{claimLabel[agent]}</p>
        </div>
        <div className="flex shrink-0 justify-end">
          <AnimatePresence mode="wait">
            {status && (
              <motion.span key={status} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.3, ease }}>
                <Sign kind={status}>{status}</Sign>
              </motion.span>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

export function StripBay({ step }: { step: number }) {
  const rows = log.filter((r) => r.step <= step).slice().reverse()
  return (
    <div className="flex h-full flex-col">
      <p className="font-label text-[11px] tracking-[0.12em] text-faint">STRIPS</p>
      <div className="mt-3 grid gap-2">
        <Strip agent="a" step={step} />
        <Strip agent="b" step={step} />
      </div>
      <p className="mt-7 font-label text-[11px] tracking-[0.12em] text-faint">LOG</p>
      <ol className="mt-2 font-mono text-[12px] lg:min-h-[230px]" aria-live="polite">
        <AnimatePresence initial={false}>
          {rows.map((r) => (
            <motion.li
              key={r.step}
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.4, ease }}
              className="overflow-hidden"
            >
              <div className="grid grid-cols-[64px_70px_minmax(0,1fr)] items-baseline gap-2 border-b border-line py-[7px]">
                <span className="text-faint">{r.time}</span>
                <span className={`font-label text-[11px] tracking-[0.06em] ${r.verdict === 'HOLD' ? 'font-bold text-accent' : r.verdict === 'CLEARED' ? 'text-ok' : 'text-muted'}`}>{r.verdict}</span>
                <span className="truncate text-text">
                  <span style={{ color: agents[r.agent].color }}>{agents[r.agent].id}</span> {r.subject}
                </span>
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
    </div>
  )
}
