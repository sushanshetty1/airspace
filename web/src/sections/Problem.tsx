import { motion, useInView, useReducedMotion } from 'motion/react'
import { useRef } from 'react'
import { Container, SectionHeading } from '../ui'

const ease = [0.22, 1, 0.36, 1] as const

function Pass({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <rect x={x - 54} y={y - 14} width={108} height={28} rx={7} fill="var(--bg)" />
      <rect x={x - 54} y={y - 14} width={108} height={28} rx={7} fill="var(--ok-soft)" />
      <text x={x} y={y + 5} textAnchor="middle" fontSize={14} fontWeight={600} fill="var(--ok)">
        Tests pass
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
    <svg ref={ref} viewBox="0 0 1200 380" className="block h-auto w-full" role="img" aria-label="agent-a changes slugify on one branch and its tests pass. agent-b adds a call to slugify on another branch and its tests pass. Git merges both into main with no conflict, and main breaks.">
      <text x={40} y={196} className="font-mono" fontSize={15} fontWeight={600} fill="var(--text)">
        main
      </text>
      <motion.path d="M100 191 H820" stroke="var(--line-strong)" strokeWidth={2} fill="none" {...draw(0, 0.8)} />
      <motion.path d="M820 191 H1160" stroke="var(--bad)" strokeWidth={2.5} strokeDasharray="6 7" fill="none" {...draw(2.2, 0.6)} />

      <motion.path d="M150 191 C 210 191, 210 81, 270 81 H 700 C 760 81, 760 191, 820 191" stroke="var(--agent-a)" strokeWidth={2.5} fill="none" {...draw(0.3)} />
      <motion.g {...fade(0.6)}>
        <text x={290} y={48} className="font-mono" fontSize={14} fontWeight={600} fill="var(--agent-a)">
          agent-a
        </text>
        <text x={360} y={48} fontSize={14} fill="var(--muted)">
          on refactor-slugify
        </text>
        <circle cx={356} cy={81} r={6} fill="var(--agent-a)" />
        <text x={290} y={124} className="font-mono" fontSize={15} fill="var(--text)">
          <tspan fill="var(--ok)">+ </tspan>def slugify(value, *, unicode=False):
        </text>
        <Pass x={640} y={81} />
      </motion.g>

      <motion.path d="M190 191 C 250 191, 250 301, 310 301 H 700 C 760 301, 760 191, 820 191" stroke="var(--agent-b)" strokeWidth={2.5} fill="none" {...draw(0.5)} />
      <motion.g {...fade(0.8)}>
        <text x={330} y={350} className="font-mono" fontSize={14} fontWeight={600} fill="var(--agent-b)">
          agent-b
        </text>
        <text x={400} y={350} fontSize={14} fill="var(--muted)">
          on post-permalinks
        </text>
        <circle cx={396} cy={301} r={6} fill="var(--agent-b)" />
        <text x={330} y={272} className="font-mono" fontSize={15} fill="var(--text)">
          <tspan fill="var(--ok)">+ </tspan>slug = slugify(post.title, True)
        </text>
        <Pass x={640} y={301} />
      </motion.g>

      <motion.g {...fade(1.9)}>
        <circle cx={820} cy={191} r={20} fill="none" stroke="var(--bad)" strokeWidth={1.5} strokeOpacity={0.45} />
        <circle cx={820} cy={191} r={9} fill="var(--bad)" />
        <text x={848} y={162} fontSize={14} fill="var(--muted)">
          Merged with no conflicts
        </text>
      </motion.g>
      <motion.g {...fade(2.6)}>
        <rect x={938} y={210} width={150} height={30} rx={7} fill="var(--bad)" />
        <text x={1013} y={230} textAnchor="middle" fontSize={14} fontWeight={600} fill="var(--bg)">
          Build broken
        </text>
      </motion.g>
    </svg>
  )
}

/** The same story for narrow screens: three rows instead of three lanes. */
function MergeStack() {
  const rows = [
    { who: 'agent-a', color: 'var(--agent-a)', code: 'def slugify(value, *, unicode=False):', ok: true },
    { who: 'agent-b', color: 'var(--agent-b)', code: 'slug = slugify(post.title, True)', ok: true },
    { who: 'main', color: 'var(--text)', code: 'Merged with no conflicts', ok: false },
  ]
  return (
    <div className="mt-12 divide-y divide-line overflow-hidden rounded-[12px] border border-line md:hidden">
      {rows.map((r) => (
        <div key={r.who} className="px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[13px] font-semibold" style={{ color: r.color }}>
              {r.who}
            </span>
            {r.ok ? <span className="sign sign-cleared">Tests pass</span> : <span className="sign bg-bad text-bg">Build broken</span>}
          </div>
          <p className={`mt-2 text-[13px] break-words ${r.ok ? 'font-mono text-text' : 'text-muted'}`}>
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
        <SectionHeading title="Passes alone. Fails together." lede="Each agent works on its own branch, and each branch is green. Git merges both without a conflict. Then the build breaks." />

        <div className="mt-12 overflow-hidden rounded-[14px] border border-line px-8 py-8 max-md:hidden">
          <MergeFigure />
        </div>
        <MergeStack />

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <div className="rounded-[12px] border border-line bg-surface px-5 py-4 font-mono text-[12.5px] leading-[1.75] sm:text-[13px]">
            <p className="text-bad">FAILED tests/test_views.py::test_render_post</p>
            <p className="text-text">TypeError: slugify() takes 1 positional argument but 2 were given</p>
          </div>
          <p className="self-center text-[17px] leading-relaxed text-muted text-pretty lg:px-4">
            Git compares lines. It cannot see that agent-b's new call depends on the function agent-a is rewriting. A graph can.
          </p>
        </div>
      </Container>
    </section>
  )
}
