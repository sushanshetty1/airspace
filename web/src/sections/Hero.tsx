import { ArrowRight } from '@phosphor-icons/react'
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useRef, useState } from 'react'
import { TowerApp } from '../radar/TowerApp'
import { useStory } from '../radar/story'
import { ButtonLink, Container, REPO_URL } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function LiveTower() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.15 })
  const reduced = useReducedMotion() ?? false
  const [paused, setPaused] = useState(false)
  const step = useStory(inView && !paused, reduced)
  return (
    <div ref={ref}>
      <TowerApp step={step} paused={paused} onTogglePause={() => setPaused((p) => !p)} showControls={!reduced} />
    </div>
  )
}

export function Hero() {
  return (
    <section id="top" className="relative pt-16 pb-24 sm:pt-24 sm:pb-32">
      <Container>
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease }}
          className="display max-w-[880px] text-[44px] text-balance sm:text-[64px] lg:text-[76px]"
        >
          Air-traffic control for coding agents.
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease, delay: 0.08 }}
          className="mt-6 max-w-[540px] text-[18px] leading-relaxed text-muted text-pretty sm:text-[20px]"
        >
          Run several Claude Code sessions on one feature. A graph of your code decides which edit would break another agent's work, and Airspace holds it before it is written.
        </motion.p>
        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease, delay: 0.16 }} className="mt-9 flex flex-wrap gap-3">
          <ButtonLink href="#tower">
            See it run <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
          </ButtonLink>
          <ButtonLink href={REPO_URL} variant="secondary">
            View on GitHub
          </ButtonLink>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 1, ease, delay: 0.25 }} className="mt-16 sm:mt-20">
          <LiveTower />
        </motion.div>
      </Container>
    </section>
  )
}
