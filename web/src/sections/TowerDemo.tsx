import { ArrowCounterClockwise, ChatCircleText, LockOpen, PauseCircle, PlayCircle } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Terminal, type TermLine } from '../Terminal'
import { Container, Frame, LogoMark, SectionHeading, Sign } from '../ui'

type Outcome = 'held' | 'messaged' | 'released'

const baseLines: TermLine[] = [
  { kind: 'prompt', text: 'add permalinks to post pages' },
  { kind: 'tool', text: 'Update(blog/views.py)' },
  { kind: 'diff', text: '+ slug = slugify(post.title, True)' },
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="HOLD">Hold</Sign> Airspace held this edit
      </>
    ),
    lines: ['utils.text.slugify is being changed by agent-a', 'path   render_post -> slugify'],
  },
]

const messageLines: TermLine[] = [
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="BRIEFED">Message</Sign> from Tower
      </>
    ),
    lines: ['Use slugify(post.title, unicode=True).'],
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

const releaseLines: TermLine[] = [
  {
    kind: 'result',
    head: (
      <>
        <Sign kind="CLEARED">Cleared</Sign> Hold released from Tower
      </>
    ),
    lines: ['Updated blog/views.py'],
  },
]

function Action({ onClick, disabled, primary, pressed, children }: { onClick: () => void; disabled?: boolean; primary?: boolean; pressed?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={pressed}
      className={`inline-flex h-10 items-center gap-2 rounded-[8px] px-3.5 text-[14px] font-semibold transition-[transform,opacity,background-color,color] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-35 ${
        primary ? 'bg-accent text-accent-ink hover:brightness-[1.07]' : 'text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2'
      }`}
    >
      {children}
    </button>
  )
}

export function TowerDemo() {
  const [outcome, setOutcome] = useState<Outcome>('held')
  const [extra, setExtra] = useState<TermLine[]>([])
  const [pausedA, setPausedA] = useState(false)
  const timers = useRef<number[]>([])

  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t))
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  const play = (lines: TermLine[]) => {
    clearTimers()
    lines.forEach((line, i) => {
      timers.current.push(window.setTimeout(() => setExtra((prev) => [...prev, line]), 350 + i * 650))
    })
  }

  const reset = () => {
    clearTimers()
    setOutcome('held')
    setExtra([])
    setPausedA(false)
  }

  const resolved = outcome !== 'held'

  return (
    <section id="tower" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading
          title="See every agent. Step in from the browser."
          lede="Tower shows what each agent is doing and why it was held. What you decide there reaches the agent on its next step. Try it."
        />

        <div className="mt-12 grid items-stretch gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <Terminal agent="agent-b" color="var(--agent-b)" lines={[...baseLines, ...extra]} className="h-full" />

          <Frame
            title={
              <>
                <LogoMark className="h-[13px] w-auto text-text" />
                <span className="font-semibold text-text">Tower</span>
                <span className="text-faint">/</span>
                <span className="truncate font-mono text-muted">collisions / c_0007</span>
              </>
            }
            right={outcome === 'held' ? <Sign kind="HOLD">Hold</Sign> : <Sign kind="CLEARED">{outcome === 'messaged' ? 'Resolved' : 'Released'}</Sign>}
          >
            <div className="divide-y divide-line">
              <div className="px-5 py-5">
                <p className="text-[13px] font-semibold text-muted">Why it was held</p>
                <p className="mt-2.5 text-[15px] leading-[2.1] text-muted">
                  <span className="font-mono font-semibold text-agent-b">agent-b</span>'s edit makes <Sign kind="LOCATION">render_post</Sign> call{' '}
                  <Sign kind="LOCATION">slugify</Sign>, which <span className="font-mono font-semibold text-agent-a">agent-a</span> is changing.
                </p>
              </div>

              <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-3 px-5 py-5 font-mono text-[12.5px]">
                <dt className="text-agent-a">agent-a has</dt>
                <dd className="break-words text-text">slugify(value, *, unicode=False)</dd>
                <dt className="text-agent-b">agent-b wrote</dt>
                <dd className="break-words text-text">
                  slugify(post.title, <span className="bg-accent px-1 text-accent-ink">True</span>)
                </dd>
              </dl>

              <div className="px-5 py-5">
                <div className="flex flex-wrap gap-2">
                  <Action
                    primary
                    disabled={resolved}
                    onClick={() => {
                      setOutcome('messaged')
                      play(messageLines)
                    }}
                  >
                    <ChatCircleText size={17} weight="bold" /> Message agent-b
                  </Action>
                  <Action
                    disabled={resolved}
                    onClick={() => {
                      setOutcome('released')
                      play(releaseLines)
                    }}
                  >
                    <LockOpen size={17} weight="bold" /> Release hold
                  </Action>
                  <Action pressed={pausedA} onClick={() => setPausedA((p) => !p)}>
                    {pausedA ? <PlayCircle size={17} weight="bold" /> : <PauseCircle size={17} weight="bold" />}
                    {pausedA ? 'Resume agent-a' : 'Pause agent-a'}
                  </Action>
                </div>

                <div className="mt-4 min-h-[48px] text-[14px] leading-relaxed" aria-live="polite">
                  <AnimatePresence mode="wait">
                    <motion.p
                      key={`${outcome}-${pausedA}`}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.25 }}
                      className={outcome === 'released' ? 'text-accent' : 'text-muted'}
                    >
                      {outcome === 'held' &&
                        (pausedA ? 'agent-a is paused. Its next edit will be held until you resume it.' : 'Send agent-b the new signature, or release the hold yourself.')}
                      {outcome === 'messaged' && 'agent-b used the new signature. Both changes can merge.'}
                      {outcome === 'released' && 'Released. agent-b still calls the old signature, so its tests will fail after the merge.'}
                    </motion.p>
                  </AnimatePresence>
                  {resolved && (
                    <button type="button" onClick={reset} className="mt-2 inline-flex items-center gap-1.5 text-[14px] font-semibold text-text hover:text-accent">
                      <ArrowCounterClockwise size={14} weight="bold" /> Replay
                    </button>
                  )}
                </div>
              </div>
            </div>
          </Frame>
        </div>
      </Container>
    </section>
  )
}
