import { ArrowRight, Pause, Play } from '@phosphor-icons/react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useRef, useState } from 'react'
import { Scope } from '../radar/Scope'
import { StripBay } from '../radar/Strips'
import { useStory } from '../radar/story'
import { Brackets, ButtonLink, Container, Fig, REPO_URL } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Console() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.15 })
  const reduced = useReducedMotion() ?? false
  const [paused, setPaused] = useState(false)
  const step = useStory(inView && !paused, reduced)

  return (
    <div ref={ref}>
      <div className="flex items-center justify-between gap-4">
        <Fig n="01">Two agents, one codebase, one collision</Fig>
        {!reduced && (
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            className="inline-flex items-center gap-2 font-label text-[11px] tracking-[0.12em] text-muted transition-colors hover:text-text"
          >
            {paused ? <Play size={12} weight="fill" /> : <Pause size={12} weight="fill" />}
            {paused ? 'PLAY' : 'PAUSE'}
          </button>
        )}
      </div>
      <Brackets className="mt-4">
        <div className="grid gap-8 border border-line bg-surface/40 p-4 sm:p-7 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-10">
          <Scope step={step} />
          <StripBay step={step} />
        </div>
      </Brackets>
    </div>
  )
}

export function Hero() {
  return (
    <section id="top" className="relative pt-14 pb-24 sm:pt-20 sm:pb-32">
      <Container>
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease }}
          className="display max-w-[1180px] text-[40px] text-balance sm:text-[62px] lg:text-[80px]"
        >
          Air-traffic control for coding agents.
        </motion.h1>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease, delay: 0.1 }}
          className="mt-8 flex flex-col gap-7 lg:flex-row lg:items-end lg:justify-between"
        >
          <p className="max-w-[540px] text-[18px] leading-relaxed text-muted text-pretty sm:text-[20px]">
            Run several Claude Code sessions on one feature. Airspace holds the edit that would break another agent's work.
          </p>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href="#tower">
              See it run <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
            </ButtonLink>
            <ButtonLink href={REPO_URL} variant="secondary">
              View on GitHub
            </ButtonLink>
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, ease, delay: 0.22 }} className="mt-14 sm:mt-20">
          <Console />
        </motion.div>
      </Container>
    </section>
  )
}
