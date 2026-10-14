import { motion, useInView, useReducedMotion } from 'motion/react'
import { useRef } from 'react'
import { Brackets, Container, Fig, SectionHeading } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Pass({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <rect x={x - 62} y={y - 13} width={124} height={26} rx={2} fill="var(--bg)" stroke="var(--ok)" strokeWidth={1.5} />
      <text x={x} y={y + 4.5} textAnchor="middle" className="font-mono" fontSize={12} fontWeight={700} letterSpacing={1.2} fill="var(--ok)">
        TESTS PASS
      </text>
    </g>
  )
}

/** Two branches, both green, merged into main. The break only exists after the merge. */
function MergeFigure() {
  const ref = useRef<SVGSVGElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.4 })
  const reduced = useReducedMotion()
  const show = reduced || inView
  const draw = (delay: number, duration = 1.1) => ({
    initial: { pathLength: reduced ? 1 : 0 },
    animate: { pathLength: show ? 1 : 0 },
    transition: { duration: reduced ? 0 : duration, ease, delay },
  })
  const fade = (delay: number) => ({
    initial: { opacity: reduced ? 1 : 0 },
    animate: { opacity: show ? 1 : 0 },
    transition: { duration: reduced ? 0 : 0.5, delay },
  })

  return (
    <svg ref={ref} viewBox="0 0 1200 390" className="block h-auto w-full" role="img" aria-label="agent-a changes slugify on one branch and its tests pass. agent-b adds a call to slugify on another branch and its tests pass. Git merges both into main with no conflict, and main breaks.">
      {/* main */}
      <text x={40} y={201} className="font-mono" fontSize={14} fontWeight={700} fill="var(--text)">
        main
      </text>
      <motion.path d="M100 196 H820" stroke="var(--line-strong)" strokeWidth={2} fill="none" {...draw(0, 0.8)} />
      <motion.path d="M820 196 H1160" stroke="var(--bad)" strokeWidth={2.5} strokeDasharray="6 7" fill="none" {...draw(2.2, 0.6)} />

      {/* agent-a */}
      <motion.path d="M150 196 C 210 196, 210 86, 270 86 H 700 C 760 86, 760 196, 820 196" stroke="var(--agent-a)" strokeWidth={2.5} fill="none" {...draw(0.3)} />
      <motion.g {...fade(0.6)}>
        <text x={290} y={52} className="font-mono" fontSize={13} fontWeight={700} letterSpacing={1.2} fill="var(--agent-a)">
          AGENT-A
        </text>
        <text x={380} y={52} className="font-mono" fontSize={13} fill="var(--muted)">
          refactor-slugify
        </text>
        <rect x={350} y={80} width={12} height={12} fill="var(--agent-a)" />
        <text x={290} y={128} className="font-mono" fontSize={15} fill="var(--text)">
          <tspan fill="var(--ok)">+ </tspan>def slugify(value, *, unicode=False):
        </text>
        <Pass x={640} y={86} />
      </motion.g>

      {/* agent-b */}
      <motion.path d="M190 196 C 250 196, 250 306, 310 306 H 700 C 760 306, 760 196, 820 196" stroke="var(--agent-b)" strokeWidth={2.5} fill="none" {...draw(0.5)} />
      <motion.g {...fade(0.8)}>
        <text x={330} y={362} className="font-mono" fontSize={13} fontWeight={700} letterSpacing={1.2} fill="var(--agent-b)">
          AGENT-B
        </text>
        <text x={420} y={362} className="font-mono" fontSize={13} fill="var(--muted)">
          post-permalinks
        </text>
        <rect x={390} y={300} width={12} height={12} fill="var(--agent-b)" />
        <text x={330} y={276} className="font-mono" fontSize={15} fill="var(--text)">
          <tspan fill="var(--ok)">+ </tspan>slug = slugify(post.title, True)
        </text>
        <Pass x={640} y={306} />
      </motion.g>

      {/* the merge */}
      <motion.g {...fade(1.9)}>
        <circle cx={820} cy={196} r={20} fill="none" stroke="var(--bad)" strokeWidth={1.5} strokeOpacity={0.5} />
        <circle cx={820} cy={196} r={10} fill="var(--bad)" />
        <text x={850} y={168} className="font-mono" fontSize={12.5} fill="var(--muted)">
          git merge: no conflicts
        </text>
      </motion.g>
      <motion.g {...fade(2.6)}>
        <rect x={938} y={214} width={176} height={28} rx={2} fill="var(--bad)" />
        <text x={1026} y={233} textAnchor="middle" className="font-mono" fontSize={12.5} fontWeight={700} letterSpacing={1.4} fill="var(--bg)">
          BUILD BROKEN
        </text>
      </motion.g>
    </svg>
  )
}

/** The same story for narrow screens: three rows instead of three lanes. */
function MergeStack() {
  const rows = [
    { who: 'AGENT-A', color: 'var(--agent-a)', code: 'def slugify(value, *, unicode=False):', ok: true },
    { who: 'AGENT-B', color: 'var(--agent-b)', code: 'slug = slugify(post.title, True)', ok: true },
    { who: 'MAIN', color: 'var(--text)', code: 'git merge: no conflicts', ok: false },
  ]
  return (
    <div className="mt-4 divide-y divide-line border border-line md:hidden">
      {rows.map((r) => (
        <div key={r.who} className="px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <span className="font-label text-[12px] font-bold tracking-[0.06em]" style={{ color: r.color }}>
              {r.who}
            </span>
            {r.ok ? <span className="sign sign-cleared">TESTS PASS</span> : <span className="sign bg-bad text-bg">BUILD BROKEN</span>}
          </div>
          <p className="mt-2 font-mono text-[12.5px] break-words text-text">
            {r.ok && <span className="text-ok">+ </span>}
            {r.code}
          </p>
        </div>
      ))}
    </div>
  )
}

export function Problem() {
  return (
    <section id="problem" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading
          title="Passes alone. Fails together."
          lede="Each agent works on its own branch, and each branch is green. Git merges both without a conflict. Then the build breaks."
        />

        <Fig n="02" className="mt-14">
          Two green branches, one red main
        </Fig>
        <Brackets className="mt-4 max-md:hidden">
          <div className="border border-line px-8 py-8">
            <MergeFigure />
          </div>
        </Brackets>
        <MergeStack />

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <div className="border border-line bg-surface px-5 py-4 font-mono text-[12.5px] leading-[1.75] sm:text-[13px]">
            <p className="text-bad">FAILED tests/test_views.py::test_render_post</p>
            <p className="text-text">TypeError: slugify() takes 1 positional argument but 2 were given</p>
          </div>
          <p className="self-center text-[16px] leading-relaxed text-muted text-pretty lg:px-4">
            Git compares lines. It cannot see that agent-b's new call depends on the function agent-a is rewriting. A graph can.
          </p>
        </div>
      </Container>
    </section>
  )
}
