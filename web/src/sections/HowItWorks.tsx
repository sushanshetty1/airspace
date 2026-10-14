import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Scope } from '../radar/Scope'
import { Line, type TermLine } from '../Terminal'
import { Container, SectionHeading, Sign } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

type Step = { title: string; body: string; scope: number; agent: string; color: string; lines: TermLine[] }

const steps: Step[] = [
  {
    title: 'File a flight plan',
    body: 'An agent says what it will change. Airspace maps everything that calls, overrides or tests it.',
    scope: 1,
    agent: 'agent-a',
    color: 'var(--agent-a)',
    lines: [
      { kind: 'tool', text: 'airspace · file_flight_plan(["utils.text.slugify"])' },
      {
        kind: 'result',
        head: (
          <>
            <Sign kind="FILED">Plan filed</Sign> Impact cone: 6 symbols
          </>
        ),
      },
    ],
  },
  {
    title: 'Ask before every write',
    body: "A Claude Code hook checks each edit. Inside the agent's own airspace it is cleared. Inside another agent's, it is held.",
    scope: 5,
    agent: 'agent-b',
    color: 'var(--agent-b)',
    lines: [
      { kind: 'tool', text: 'Update(blog/views.py)' },
      {
        kind: 'result',
        head: (
          <>
            <Sign kind="HOLD">Hold</Sign> slugify is changing in agent-a
          </>
        ),
        lines: ['path   render_post → slugify'],
      },
    ],
  },
  {
    title: "Brief, don't surprise",
    body: 'When a signature changes, every agent that depends on it gets the new one on its next step.',
    scope: 7,
    agent: 'agent-b',
    color: 'var(--agent-b)',
    lines: [
      {
        kind: 'result',
        head: (
          <>
            <Sign kind="BRIEFED">Briefed</Sign> slugify(value, *, unicode=False)
          </>
        ),
      },
      { kind: 'tool', text: 'Update(blog/views.py)' },
      {
        kind: 'result',
        head: (
          <>
            <Sign kind="CLEARED">Cleared</Sign> Updated blog/views.py
          </>
        ),
      },
    ],
  },
]

/** The airspaces at this step, with what the agent's terminal printed laid over the corner. */
function Visual({ step }: { step: Step }) {
  return (
    <div className="relative overflow-hidden rounded-[16px] border border-line bg-surface">
      <div className="px-3 pt-8 pb-4 sm:px-10 sm:pt-12 sm:pb-40">
        <Scope step={step.scope} />
      </div>
      <div className="m-3 mt-0 sm:absolute sm:bottom-5 sm:left-5 sm:m-0 sm:w-[420px]">
        <AnimatePresence mode="wait">
          <motion.div
            key={step.title}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.35, ease }}
            className="rounded-[12px] border border-line-strong bg-bg/95 px-4 py-3.5 font-mono text-[12.5px] leading-[1.7] shadow-[0_18px_40px_-20px_rgb(0_0_0/0.5)] backdrop-blur"
          >
            <p className="mb-2 text-[12px]" style={{ color: step.color }}>
              {step.agent}
            </p>
            <div className="space-y-2">
              {step.lines.map((l, i) => (
                <Line key={i} line={l} />
              ))}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

export function HowItWorks() {
  const [active, setActive] = useState(0)
  const refs = useRef<(HTMLDivElement | null)[]>([])

  // The step crossing the middle of the screen is the one the visual shows.
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.index))
      },
      { rootMargin: '-50% 0px -50% 0px' },
    )
    refs.current.forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [])

  return (
    <section id="how" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading title="Every edit asks first." lede="Airspace checks each write against the code graph before it lands. The answer is a graph query and a few rules, never a model call." />

        <div className="mt-12 grid gap-10 lg:mt-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-16">
          <div>
            {steps.map((s, i) => (
              <div
                key={s.title}
                ref={(el) => {
                  refs.current[i] = el
                }}
                data-index={i}
                className="py-10 lg:flex lg:min-h-[78vh] lg:flex-col lg:justify-center lg:py-0"
              >
                <h3 className={`text-[28px] leading-tight font-semibold tracking-[-0.025em] transition-colors duration-500 sm:text-[32px] ${active === i ? 'text-text' : 'lg:text-faint'}`}>
                  {s.title}
                </h3>
                <p className={`mt-3 max-w-[38ch] text-[18px] leading-relaxed transition-colors duration-500 ${active === i ? 'text-muted' : 'lg:text-faint'}`}>{s.body}</p>
                <div className="mt-8 lg:hidden">
                  <Visual step={s} />
                </div>
              </div>
            ))}
          </div>

          <div className="hidden lg:block">
            <div className="sticky top-[calc(50vh-260px)]">
              <Visual step={steps[active]} />
            </div>
          </div>
        </div>
      </Container>
    </section>
  )
}
