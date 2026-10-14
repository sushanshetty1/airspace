import { ArrowRight } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, Fig, SectionHeading, Sign } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Cell({ title, body, className = '', children, delay = 0 }: { title: string; body: string; className?: string; children: ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, ease, delay }}
      className={`flex min-w-0 flex-col ${className}`}
    >
      <div className="p-6 sm:p-8">
        <h3 className="text-[21px] font-semibold tracking-[-0.01em]">{title}</h3>
        <p className="mt-2 max-w-[46ch] text-[15px] leading-relaxed text-muted text-pretty">{body}</p>
      </div>
      <div className="mt-auto">{children}</div>
    </motion.div>
  )
}

function Rel({ label, back }: { label: string; back?: boolean }) {
  return (
    <span className="flex shrink-0 items-center gap-1.5 font-label text-[11px] tracking-[0.1em] text-faint">
      {back && <ArrowRight size={12} weight="bold" className="rotate-180" />}
      {label}
      {!back && <ArrowRight size={12} weight="bold" />}
    </span>
  )
}

function Group({ name, tasks, hot }: { name: string; tasks: { id: string; color: string }[]; hot?: boolean }) {
  return (
    <div className={`border border-dashed p-3 ${hot ? 'border-accent' : 'border-line-strong'}`}>
      <p className={`font-label text-[10.5px] tracking-[0.12em] ${hot ? 'text-accent' : 'text-faint'}`}>{name}</p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {tasks.map((t) => (
          <span key={t.id} className="px-2 py-1 font-mono text-[12px] font-bold text-ink" style={{ background: t.color }}>
            {t.id.toUpperCase()}
          </span>
        ))}
      </div>
    </div>
  )
}

export function WhyGraph() {
  return (
    <section id="graph" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading
          title="A collision is a path."
          lede="Airspace keeps your code and your agents in one FalkorDB graph. Finding the collision, and explaining it, is a single query."
        />

        <Fig n="05" className="mt-14">
          What the graph does
        </Fig>
        <div className="mt-4 grid grid-cols-1 gap-px border border-line bg-line lg:grid-cols-3">
          <Cell className="bg-bg lg:col-span-2" title="The path is the explanation." body="agent-b's new call reaches agent-a's change in one hop. That path is what the agent reads and what Tower shows.">
            <div className="flex items-center gap-3 overflow-x-auto border-t border-line px-6 py-7 sm:px-8">
              <span className="shrink-0 font-mono text-[13px] font-bold text-agent-b">AGENT-B</span>
              <Rel label="EDITS" />
              <Sign kind="LOCATION" className="h-8 shrink-0 px-3 text-[12.5px] normal-case tracking-normal">
                render_post
              </Sign>
              <Rel label="CALLS" />
              <Sign kind="LOCATION" className="h-8 shrink-0 px-3 text-[12.5px] normal-case tracking-normal">
                slugify
              </Sign>
              <Rel label="CLAIMS" back />
              <span className="shrink-0 font-mono text-[13px] font-bold text-agent-a">AGENT-A</span>
            </div>
          </Cell>

          <Cell className="bg-accent text-accent-ink [&_p]:text-accent-ink/75" title="A query, not a model call." body="Clearance is Cypher and a few rules. Fast, repeatable, and it never guesses." delay={0.08}>
            <pre className="overflow-x-auto px-6 pb-8 font-mono text-[12px] leading-[1.75] sm:px-8">
              {`MATCH (t:Symbol {qualname: $q})
MATCH (o:Task)-[:CONE|CLAIMS]->(t)
WHERE o.id <> $task
RETURN o.id, o.intent`}
            </pre>
          </Cell>

          <Cell className="bg-bg" title="Parallel by default." body="Connected components split tasks into groups. Groups fly at once; only tasks that touch wait." delay={0.04}>
            <div className="grid gap-2 px-6 pb-8 sm:px-8">
              <Group
                hot
                name="GROUP 1 · COORDINATE"
                tasks={[
                  { id: 'agent-a', color: 'var(--agent-a)' },
                  { id: 'agent-b', color: 'var(--agent-b)' },
                ]}
              />
              <div className="grid grid-cols-2 gap-2">
                <Group name="GROUP 2" tasks={[{ id: 'agent-c', color: 'var(--muted)' }]} />
                <Group name="GROUP 3" tasks={[{ id: 'agent-d', color: 'var(--muted)' }]} />
              </div>
            </div>
          </Cell>

          <Cell className="bg-bg lg:col-span-2" title="It remembers." body="Holds and contract changes stay in the graph. Next session, the planner knows the hot zones and splits work around them." delay={0.12}>
            <div className="grid border-t border-line sm:grid-cols-2">
              <div className="px-6 py-6 sm:border-r sm:border-line sm:px-8">
                <div className="flex items-center gap-3">
                  <span className="font-label text-[11px] tracking-[0.12em] text-faint">SESSION 1</span>
                  <Sign kind="HOLD">HOLD</Sign>
                </div>
                <p className="mt-3 text-[15px] leading-relaxed text-text">
                  agent-a and agent-b collide at <span className="font-mono">slugify</span>. One hold, one briefing.
                </p>
              </div>
              <div className="border-t border-line px-6 py-6 sm:border-t-0 sm:px-8">
                <div className="flex items-center gap-3">
                  <span className="font-label text-[11px] tracking-[0.12em] text-faint">SESSION 2</span>
                  <Sign kind="CLEARED">CLEARED</Sign>
                </div>
                <p className="mt-3 text-[15px] leading-relaxed text-text">
                  The planner gives <span className="font-mono">slugify</span> and its callers to one agent. No collision.
                </p>
              </div>
            </div>
          </Cell>
        </div>

        <div className="mt-6 flex items-center gap-3 text-[14px] text-muted">
          <img src="/logos/falkordb.svg" alt="" className="size-6" />
          <p>
            Built on{' '}
            <a href="https://www.falkordb.com" className="font-semibold text-text underline decoration-line-strong underline-offset-4 hover:decoration-text">
              FalkorDB
            </a>
            , with one graph per repo and its built-in path and component algorithms.
          </p>
        </div>
      </Container>
    </section>
  )
}
