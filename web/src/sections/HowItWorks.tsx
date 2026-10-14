import { AnimatePresence, motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Scope } from '../radar/Scope'
import { Terminal, type TermLine } from '../Terminal'
import { Container, SectionHeading, Sign } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

const holdLines: TermLine[] = [
  { kind: 'tool', text: 'Update(blog/views.py)' },
  { kind: 'diff', text: '+ slug = slugify(post.title, True)' },
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="HOLD">Hold</Sign> Airspace held this edit
      </>
    ),
    lines: ['utils.text.slugify is changing in agent-a', 'path   render_post → slugify'],
  },
]

const briefLines: TermLine[] = [
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="BRIEFED">Briefed</Sign> slugify has a new signature
      </>
    ),
    lines: ['new    slugify(value, *, unicode=False)', 'Update your call, then try again.'],
  },
  { kind: 'tool', text: 'Update(blog/views.py)' },
  { kind: 'diff', text: '+ slug = slugify(post.title, unicode=True)' },
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="CLEARED">Cleared</Sign> Updated blog/views.py
      </>
    ),
  },
]

const steps = [
  { title: 'File a flight plan', body: 'An agent says what it will change. Airspace maps everything that calls, imports or tests it, ring by ring.' },
  { title: 'Ask before every write', body: "A Claude Code hook checks each edit. Inside the agent's own airspace it is cleared. Inside another agent's, it is held." },
  { title: "Brief, don't surprise", body: 'When a signature changes, every agent that depends on it gets the new one on its next step.' },
]

function Visual({ index }: { index: number }) {
  if (index === 0) {
    return (
      <div className="rounded-[14px] border border-line bg-surface px-3 py-6 sm:px-8 sm:py-8">
        <Scope step={2} />
      </div>
    )
  }
  return <Terminal agent="agent-b" color="var(--agent-b)" lines={index === 1 ? holdLines : briefLines} />
}

export function HowItWorks() {
  const [active, setActive] = useState(0)
  const [touched, setTouched] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.4 })
  const reduced = useReducedMotion()

  useEffect(() => {
    if (touched || !inView || reduced) return
    const id = window.setTimeout(() => setActive((a) => (a + 1) % steps.length), 6500)
    return () => window.clearTimeout(id)
  }, [active, touched, inView, reduced])

  return (
    <section id="how" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading title="Every edit asks first." lede="Airspace checks each write against the code graph before it lands. The answer is a graph query and a few rules, never a model call." />

        <div ref={ref} className="mt-14 grid gap-8 lg:grid-cols-[360px_minmax(0,1fr)] lg:gap-14">
          <div className="flex flex-col" role="tablist" aria-label="How Airspace works">
            {steps.map((s, i) => {
              const on = i === active
              return (
                <button
                  key={s.title}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => {
                    setActive(i)
                    setTouched(true)
                  }}
                  className="group relative border-t border-line py-6 text-left last:border-b"
                >
                  <span className={`block text-[20px] font-semibold tracking-[-0.01em] transition-colors ${on ? 'text-text' : 'text-muted group-hover:text-text'}`}>{s.title}</span>
                  <AnimatePresence initial={false}>
                    {on && (
                      <motion.span
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.35, ease }}
                        className="block overflow-hidden"
                      >
                        <span className="block pt-2 text-[15px] leading-relaxed text-muted">{s.body}</span>
                      </motion.span>
                    )}
                  </AnimatePresence>
                  {on && !touched && !reduced && (
                    <motion.span
                      key={`bar-${active}`}
                      className="absolute -top-px left-0 h-[2px] bg-accent"
                      initial={{ width: '0%' }}
                      animate={{ width: inView ? '100%' : '0%' }}
                      transition={{ duration: 6.5, ease: 'linear' }}
                    />
                  )}
                </button>
              )
            })}
          </div>

          <div className="min-w-0">
            <div>
              <AnimatePresence mode="wait">
                <motion.div key={active} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35, ease }}>
                  <Visual index={active} />
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>
      </Container>
    </section>
  )
}
