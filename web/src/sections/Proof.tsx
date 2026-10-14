import { ArrowUpRight } from '@phosphor-icons/react'
import { useState } from 'react'
import blogBench from '../data/benchmark.json'
import flaskBench from '../data/benchmark-flask.json'
import { Container, PAPER_URL, REPO_URL, SectionHeading } from '../ui'

type Condition = 'worktrees' | 'broadcast' | 'airspace'

const conditions: { id: Condition; name: string; note: string }[] = [
  { id: 'worktrees', name: 'Worktrees only', note: "Today's default. Each agent on its own branch." },
  { id: 'broadcast', name: 'Broadcast', note: "Each agent is also told the other's task." },
  { id: 'airspace', name: 'Airspace', note: 'Clearance, briefings and the holding pattern.' },
]

// What each task pair changes, as a reader would say it.
const setNames: Record<string, string> = {
  'slugify-keyword-only': 'A keyword argument is renamed',
  'truncate-words-limit': 'A parameter becomes keyword-only',
  'rename-absolute-url': 'A method is renamed',
  'render-post-show-body': 'A required parameter is added',
  'post-requires-author': 'A constructor gains an argument',
  'tag-save-returns-none': 'A method stops returning a value',
  'flask-flash-categories': 'get_flashed_messages renames a keyword',
  'flask-debug-rename': 'get_debug_flag is renamed',
  'flask-send-file-name': 'send_file renames a keyword',
}

type Totals = { pairs: number; merged_pass: number; median_wall_seconds: number; cost_usd: number }
type Bench = { conditions: Record<Condition, Totals>; sets: Record<string, Record<Condition, boolean[]>> }

const suites: { id: string; label: string; data: Bench; results: string; where: string; note: string }[] = [
  {
    id: 'flask',
    label: 'Flask',
    data: flaskBench,
    results: 'flask',
    where: 'on Flask',
    note: "Flask's real code: 83 files, graded with its own 491 tests plus a hidden test for each agent. Agent A changes part of Flask's public API while agent B adds a feature that uses it.",
  },
  {
    id: 'blog',
    label: 'Sample blog',
    data: blogBench,
    results: 'final',
    where: 'on the sample blog',
    note: 'A small blog app with six kinds of contract change. Constructed tasks show that coordination works, not how often the problem happens in practice.',
  },
]

function Runs({ runs, ours }: { runs: boolean[]; ours?: boolean }) {
  return (
    <span className="flex gap-[3px] sm:gap-1" aria-label={`${runs.filter(Boolean).length} of ${runs.length} merged green`}>
      {runs.map((ok, i) => (
        <span
          key={i}
          className={`h-2.5 w-2.5 rounded-[2px] sm:h-3.5 sm:w-3.5 sm:rounded-[3px] ${ok ? (ours ? 'bg-accent' : 'bg-text') : 'shadow-[inset_0_0_0_1.5px_var(--line-strong)]'}`}
        />
      ))}
    </span>
  )
}

export function Proof() {
  const [suiteId, setSuiteId] = useState('flask')
  const suite = suites.find((x) => x.id === suiteId) ?? suites[0]
  const bench = suite.data
  const RESULTS_URL = `${REPO_URL}/tree/main/server/bench/results/${suite.results}`
  const c = bench.conditions
  const ours = c.airspace
  return (
    <section id="proof" className="border-t border-line py-24 sm:py-32">
      <Container>
        <SectionHeading
          title="Measured, not claimed."
          lede="Two real Claude Code agents per task, at the same time, on the same repo. Each pair runs three ways, three times. What counts is whether the merged build passes its tests."
        />

        <div role="tablist" aria-label="Benchmark repo" className="mt-10 inline-flex rounded-[10px] p-1 shadow-[inset_0_0_0_1px_var(--line)]">
          {suites.map((x) => (
            <button
              key={x.id}
              type="button"
              role="tab"
              aria-selected={x.id === suite.id}
              onClick={() => setSuiteId(x.id)}
              className={`h-9 rounded-[7px] px-4 text-[14px] font-semibold transition-colors ${x.id === suite.id ? 'bg-surface-2 text-text' : 'text-muted hover:text-text'}`}
            >
              {x.label}
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div className="flex flex-col justify-between rounded-[14px] border border-line bg-surface p-7 sm:p-9">
            <div>
              <p className="display text-[88px] sm:text-[112px]">
                {ours.merged_pass}
                <span className="text-faint">/{ours.pairs}</span>
              </p>
              <p className="mt-4 max-w-[34ch] text-[16px] leading-relaxed text-muted text-pretty">
                parallel pairs {suite.where} merged green with Airspace. {c.worktrees.merged_pass} of {c.worktrees.pairs} with worktrees alone,{' '}
                {c.broadcast.merged_pass} of {c.broadcast.pairs} when each agent knew the other's task.
              </p>
            </div>
            <div className="mt-10 flex flex-col gap-2.5">
              <a href={RESULTS_URL} className="inline-flex items-center gap-1.5 text-[14.5px] font-semibold text-text hover:text-accent">
                Every run, diff and test log <ArrowUpRight size={15} weight="bold" />
              </a>
              <a href={PAPER_URL} className="inline-flex items-center gap-1.5 text-[14.5px] font-semibold text-muted hover:text-accent">
                Method from Passes Alone, Fails Together <ArrowUpRight size={15} weight="bold" />
              </a>
            </div>
          </div>

          <div className="overflow-hidden rounded-[14px] border border-line bg-surface">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-b border-line px-6 py-3.5 text-[13px] font-semibold text-muted sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:gap-x-10 sm:px-8">
              <span>Condition</span>
              <span>Merged green</span>
              <span className="max-sm:hidden">Median time</span>
              <span className="max-sm:hidden">Cost per pair</span>
            </div>
            {conditions.map((r) => {
              const row = c[r.id]
              const isOurs = r.id === 'airspace'
              return (
                <div
                  key={r.id}
                  className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 border-b border-line px-6 py-5 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:gap-x-10 sm:px-8 ${isOurs ? 'bg-accent-soft' : ''}`}
                >
                  <div className="min-w-0">
                    <p className={`text-[17px] font-semibold ${isOurs ? 'text-accent' : 'text-text'}`}>{r.name}</p>
                    <p className="mt-0.5 text-[14px] text-muted">{r.note}</p>
                  </div>
                  <span className={`text-right text-[17px] font-semibold tabular-nums ${isOurs ? 'text-accent' : 'text-text'}`}>
                    {row.merged_pass} of {row.pairs}
                  </span>
                  <span className="text-right text-[15px] tabular-nums text-muted max-sm:hidden">{Math.round(row.median_wall_seconds)} s</span>
                  <span className="text-right text-[15px] text-muted max-sm:hidden">${(row.cost_usd / row.pairs).toFixed(2)}</span>
                </div>
              )
            })}
            <p className="px-6 py-5 text-[14px] leading-relaxed text-muted sm:px-8">
              Airspace is slower per pair because a held agent waits for the change it depends on. That wait is the point: the work merges.
            </p>
          </div>
        </div>

        <div className="mt-4 overflow-hidden rounded-[14px] border border-line bg-surface">
          <div className="grid grid-cols-[minmax(0,1fr)_repeat(3,auto)] items-center gap-x-3 border-b border-line px-5 py-3.5 text-[13px] font-semibold text-muted sm:gap-x-12 sm:px-8">
            <span>
              <span className="max-sm:hidden">What agent A changes while agent B calls it</span>
              <span className="sm:hidden">What agent A changes</span>
            </span>
            {conditions.map((r) => (
              <span key={r.id} className={`w-[36px] text-center sm:w-[50px] ${r.id === 'airspace' ? 'text-accent' : ''}`}>
                <span className="max-sm:hidden">{r.name.split(' ')[0]}</span>
                <span className="sm:hidden">{r.name[0]}</span>
              </span>
            ))}
          </div>
          {Object.entries(bench.sets).map(([id, runs]) => (
            <div key={id} className="grid grid-cols-[minmax(0,1fr)_repeat(3,auto)] items-center gap-x-3 border-b border-line px-5 py-4 last:border-b-0 sm:gap-x-12 sm:px-8">
              <span className="min-w-0 text-[14.5px] leading-snug text-text sm:text-[15px]">{setNames[id] ?? id}</span>
              {conditions.map((r) => (
                <span key={r.id} className="flex w-[36px] justify-center sm:w-[50px]">
                  <Runs runs={runs[r.id as Condition]} ours={r.id === 'airspace'} />
                </span>
              ))}
            </div>
          ))}
        </div>
        <p className="mt-5 max-w-[760px] text-[14px] leading-relaxed text-muted text-pretty">
          Each square is one run of two agents; filled means the merge passed every test, both agents' hidden tests included. {suite.note}
        </p>
      </Container>
    </section>
  )
}
