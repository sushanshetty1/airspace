import { ArrowRight } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Container, SectionHeading, Sign } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Cell({ title, body, className = '', children, delay = 0 }: { title: string; body: string; className?: string; children: ReactNode; delay?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, ease, delay }}
      className={`flex min-w-0 flex-col overflow-hidden rounded-[14px] border border-line ${className}`}
    >
      <div className="p-6 sm:p-8">
        <h3 className="text-[21px] font-semibold tracking-[-0.015em]">{title}</h3>
        <p className="mt-2 max-w-[46ch] text-[15.5px] leading-relaxed text-muted text-pretty">{body}</p>
      </div>
      <div className="mt-auto">{children}</div>
    </motion.div>
  )
}

function Group({ name, tasks, hot }: { name: string; tasks: { id: string; color: string }[]; hot?: boolean }) {
  return (
    <div className={`rounded-[10px] p-3 ${hot ? 'bg-accent-soft' : 'bg-surface-2'}`}>
      <p className={`text-[12.5px] font-semibold ${hot ? 'text-accent' : 'text-muted'}`}>{name}</p>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {tasks.map((t) => (
          <span key={t.id} className="font-mono text-[13px] font-medium" style={{ color: t.color }}>
            {t.id}
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
        <SectionHeading title="A collision is a path." lede="Airspace keeps your code and your agents in one FalkorDB graph. Finding the collision, and explaining it, is a single query." />

        <div className="mt-12 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Cell className="bg-surface lg:col-span-2" title="The path is the explanation." body="agent-b's new call reaches agent-a's change in one hop. That path is what the agent reads and what Tower shows.">
            <p className="border-t border-line px-6 py-6 text-[15px] leading-[2.1] text-muted sm:px-8">
              <span className="font-mono font-semibold text-agent-b">agent-b</span> edits <Sign kind="LOCATION">render_post</Sign>, which calls <Sign kind="LOCATION">slugify</Sign>, which{' '}
              <span className="font-mono font-semibold text-agent-a">agent-a</span> claimed.
            </p>
          </Cell>

          <Cell className="bg-accent text-accent-ink [&_p]:text-accent-ink/75" title="A query, not a model call." body="Clearance is Cypher and a few rules. Fast, repeatable, and it never guesses." delay={0.08}>
            <pre className="overflow-x-auto px-6 pb-8 font-mono text-[12.5px] leading-[1.75] text-accent-ink sm:px-8 lg:px-6 lg:text-[12px] xl:px-8 xl:text-[12.5px]">
              {`MATCH (a:Agent)-[:FLYING]->(o:Task)
      -[c:CLAIMS]->(s:Symbol)
WHERE s.qualname = $q
  AND a.id <> $agent
  AND c.lease_until > $now
RETURN o.id, a.id`}
            </pre>
          </Cell>

          <Cell className="bg-surface" title="Parallel by default." body="Agents only wait when their work meets. Connected components over the conflict graph show who must coordinate and who is free to run." delay={0.04}>
            <div className="grid gap-2 px-6 pb-8 sm:px-8">
              <Group
                hot
                name="Must coordinate"
                tasks={[
                  { id: 'agent-a', color: 'var(--agent-a)' },
                  { id: 'agent-b', color: 'var(--agent-b)' },
                ]}
              />
              <div className="grid grid-cols-2 gap-2">
                <Group name="Free to run" tasks={[{ id: 'agent-c', color: 'var(--text)' }]} />
                <Group name="Free to run" tasks={[{ id: 'agent-d', color: 'var(--text)' }]} />
              </div>
              <a
                href="/preflight"
                className="group mt-3 inline-flex items-center gap-1.5 justify-self-start text-[15px] font-semibold text-text underline decoration-line-strong underline-offset-4 hover:decoration-text"
              >
                Plan your own tasks
                <ArrowRight size={14} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
              </a>
            </div>
          </Cell>

          <Cell
            className="bg-surface lg:col-span-2"
            title="It remembers."
            body="When a collision clears, Airspace writes the fix to the graph, on the symbol it is about. The next agent to touch that code hears it, in any later session."
            delay={0.12}
          >
            <div className="grid border-t border-line sm:grid-cols-2">
              <div className="px-6 py-6 sm:border-r sm:border-line sm:px-8">
                <div className="flex items-center gap-2.5">
                  <span className="text-[14px] font-semibold text-text">Monday</span>
                  <Sign kind="HOLD">Hold</Sign>
                </div>
                <p className="mt-2.5 text-[15px] leading-relaxed text-muted">
                  <span className="font-mono text-agent-b">agent-b</span> is held at <span className="font-mono text-text">slugify</span>, whose{' '}
                  <span className="font-mono text-text">allow_unicode</span> is gone. It clears with <span className="font-mono text-text">unicode=True</span>, and Airspace writes that fix to the
                  graph.
                </p>
              </div>
              <div className="border-t border-line px-6 py-6 sm:border-t-0 sm:px-8">
                <div className="flex items-center gap-2.5">
                  <span className="text-[14px] font-semibold text-text">Tuesday</span>
                  <Sign kind="BRIEFED">Briefed</Sign>
                </div>
                <p className="mt-2.5 text-[15px] leading-relaxed text-muted">
                  A new agent touches <span className="font-mono text-text">slugify</span>. Before it writes the call, it is told the fix: <span className="font-mono text-text">unicode=True</span>. No hold.
                </p>
              </div>
            </div>
          </Cell>
        </div>

        <div className="mt-6 flex items-center gap-3 text-[15px] text-muted">
          <img src="/logos/falkordb.svg" alt="" className="size-6 rounded-[5px]" />
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
