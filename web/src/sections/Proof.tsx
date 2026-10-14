import { ArrowUpRight } from '@phosphor-icons/react'
import { Container, Fig, PAPER_URL, SectionHeading } from '../ui'

const rows = [
  { name: 'Worktrees only', note: "Today's default. Every agent on its own branch." },
  { name: 'Broadcast', note: 'Each agent is told what the others changed.' },
  { name: 'Airspace', note: 'Graph-scoped clearance and targeted briefings.', ours: true },
]

export function Proof() {
  return (
    <section id="proof" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading title="Measured, not claimed." lede="We run the same parallel tasks three ways and count only the failures the merge itself causes." />

        <Fig n="06" className="mt-14">
          Three ways to run four agents
        </Fig>
        <div className="mt-4 grid gap-px border border-line bg-line lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div className="flex flex-col justify-between bg-bg p-7 sm:p-9">
            <div>
              <p className="display text-[84px] sm:text-[112px]">97%</p>
              <p className="mt-5 max-w-[34ch] text-[16px] leading-relaxed text-muted text-pretty">
                of constructed parallel tasks broke on merge with worktrees alone. Telling each agent what the others changed fixed 82%.
              </p>
            </div>
            <a href={PAPER_URL} className="mt-10 inline-flex items-center gap-1.5 font-label text-[12px] tracking-[0.06em] text-text hover:text-accent">
              PASSES ALONE, FAILS TOGETHER (2026) <ArrowUpRight size={14} weight="bold" />
            </a>
          </div>

          <div className="bg-bg">
            <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-6 border-b border-line px-6 py-3.5 font-label text-[11px] tracking-[0.12em] text-faint sm:gap-x-10 sm:px-8">
              <span>CONDITION</span>
              <span>MERGE FAILURES</span>
              <span className="max-sm:hidden">PARALLELISM KEPT</span>
            </div>
            {rows.map((r) => (
              <div key={r.name} className={`grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-6 border-b border-line px-6 py-5 sm:gap-x-10 sm:px-8 ${r.ours ? 'bg-accent-soft' : ''}`}>
                <div className="min-w-0">
                  <p className={`text-[17px] font-semibold ${r.ours ? 'text-accent' : 'text-text'}`}>{r.name}</p>
                  <p className="mt-0.5 text-[14px] text-muted">{r.note}</p>
                </div>
                <span className="font-mono text-[12px] text-faint">MEASURING</span>
                <span className="font-mono text-[12px] text-faint max-sm:hidden">MEASURING</span>
              </div>
            ))}
            <p className="px-6 py-5 text-[13.5px] leading-relaxed text-muted sm:px-8">
              Results land here once the runs finish. Constructed tasks show whether coordination works, not how often the problem happens in practice.
            </p>
          </div>
        </div>
      </Container>
    </section>
  )
}
