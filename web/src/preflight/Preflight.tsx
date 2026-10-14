import { ArrowRight, CaretDown, Plus, X } from '@phosphor-icons/react'
import { useEffect, useEffectEvent, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useMe } from '../account/api'
import { Footer } from '../sections/Footer'
import { Nav } from '../sections/Nav'
import { Container, sectionHref } from '../ui'
import { DEFAULT_REPOS, fetchRepos, PreflightError, runPreflight, symbolOf, type DemoRepo, type PreflightAnswer, type Target, type TaskInput } from './api'
import { taskLook, type TaskLook } from './looks'
import { Result, ResultSkeleton, TaskMark } from './Result'
import { SymbolField } from './SymbolField'

const TASKS_MIN = 2
const TASKS_MAX = 6

type Row = { id: number; name: string; symbols: string[] }

// Ready examples, so a first visit shows the point without typing.
const EXAMPLES: Record<string, TaskInput[]> = {
  flask: [
    { name: 'Routing', symbols: ['flask.sansio.scaffold.Scaffold.route'] },
    { name: 'Rule registration', symbols: ['flask.sansio.scaffold.Scaffold.add_url_rule'] },
    { name: 'Error handlers', symbols: ['flask.app.Flask.handle_user_exception'] },
    { name: 'Error lookup', symbols: ['flask.sansio.app.App._find_error_handler'] },
    { name: 'Debug flag', symbols: ['flask.helpers.get_debug_flag'] },
  ],
  blog: [
    { name: 'Slug options', symbols: ['utils.text.slugify'] },
    { name: 'Post page', symbols: ['blog.views.render_post'] },
    { name: 'Tag creation', symbols: ['tags.views.tag_create'] },
  ],
}

let nextId = 1
const rowsOf = (tasks: TaskInput[]): Row[] => tasks.map((t) => ({ id: nextId++, name: t.name, symbols: [...t.symbols] }))
const blankRows = () => rowsOf([{ name: '', symbols: [] }, { name: '', symbols: [] }])
const nameOf = (row: Row, i: number) => row.name.trim() || `Task ${taskLook(i).letter}`

function targetOf(key: string): Target {
  const cut = key.indexOf(':')
  return { kind: key.slice(0, cut) === 'workspace' ? 'workspace' : 'demo', id: key.slice(cut + 1) }
}

type Done = { answer: PreflightAnswer; looks: Record<string, TaskLook> }
type Status = { kind: 'idle' } | { kind: 'running' } | { kind: 'done'; done: Done } | { kind: 'failed'; message: string; suggestions: string[] }
/** A server message about one symbol of one task, with the server's suggestions as fixes. */
type RowError = { row: number; symbol: string; message: string; suggestions: string[] }

function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center px-6 py-14 text-center">
      <svg viewBox="0 0 150 104" className="h-14 w-auto text-line-strong" aria-hidden="true">
        <circle cx="52" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="98" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <div className="mt-5 max-w-[42ch] text-[14.5px] leading-relaxed text-muted">{children}</div>
    </div>
  )
}

function Fixes({ suggestions, onPick, className = '' }: { suggestions: string[]; onPick?: (s: string) => void; className?: string }) {
  if (!suggestions.length) return null
  return (
    <div className={`mt-2 flex flex-wrap gap-1.5 ${className}`}>
      {suggestions.map((s) =>
        onPick ? (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            aria-label={`Use ${s}`}
            className="inline-flex min-h-8 max-w-full items-center rounded-[8px] px-2.5 py-1 text-left font-mono text-[12.5px] text-text shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors [overflow-wrap:anywhere] hover:bg-surface-2"
          >
            {s}
          </button>
        ) : (
          <span key={s} className="rounded-[8px] bg-surface-2 px-2.5 py-1 font-mono text-[12.5px] text-text [overflow-wrap:anywhere]">
            {s}
          </span>
        ),
      )}
    </div>
  )
}

export default function Preflight() {
  const me = useMe()
  const [repos, setRepos] = useState<DemoRepo[]>(DEFAULT_REPOS)
  const [targetKey, setTargetKey] = useState('demo:flask')
  const [rows, setRows] = useState<Row[]>(() => rowsOf(EXAMPLES.flask))
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [last, setLast] = useState<Done | null>(null)
  const [rowError, setRowError] = useState<RowError | null>(null)
  const [missing, setMissing] = useState<Record<number, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const resultRef = useRef<HTMLDivElement>(null)
  const started = useRef(false)
  const target = useMemo(() => targetOf(targetKey), [targetKey])

  const workspaces = me.status === 'ready' && me.me.user ? me.me.workspaces : []
  const repo = target.kind === 'demo' ? repos.find((r) => r.id === target.id) : null
  const targetName = target.kind === 'demo' ? (repo?.name ?? target.id) : (workspaces.find((w) => w.id === target.id)?.name ?? 'Workspace')

  useEffect(() => {
    document.title = 'Pre-flight | Airspace'
  }, [])

  const run = async (sendRows: Row[], on: Target, scroll: boolean) => {
    const filled = sendRows.map((r, i) => ({ r, i })).filter(({ r }) => r.name.trim() || r.symbols.length)
    const gaps: Record<number, string> = {}
    for (const { r } of filled) if (!r.symbols.length) gaps[r.id] = 'Add at least one symbol.'
    const names = filled.map(({ r, i }) => nameOf(r, i))
    const twice = names.find((n, i) => names.indexOf(n) !== i)
    setMissing(gaps)
    setRowError(null)
    if (Object.keys(gaps).length) return setFormError(null)
    if (filled.length < TASKS_MIN) return setFormError('Pre-flight needs at least two tasks.')
    if (twice) return setFormError(`Two tasks are named ${twice}. Give each a different name.`)
    setFormError(null)

    const tasks: TaskInput[] = filled.map(({ r, i }) => ({ name: nameOf(r, i), symbols: r.symbols }))
    const looks = Object.fromEntries(filled.map(({ r, i }) => [nameOf(r, i), taskLook(i)]))
    setStatus({ kind: 'running' })
    try {
      const answer = await runPreflight(on, tasks)
      const done = { answer, looks }
      setLast(done)
      setStatus({ kind: 'done', done })
      const box = resultRef.current?.getBoundingClientRect()
      if (scroll && box && box.top > window.innerHeight * 0.6) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } catch (e) {
      const message = e instanceof Error ? e.message : 'The check failed.'
      const suggestions = e instanceof PreflightError ? e.suggestions : []
      const symbol = e instanceof PreflightError && e.status === 422 ? symbolOf(message) : null
      const row = symbol ? filled.find(({ r }) => r.symbols.includes(symbol))?.r : undefined
      if (symbol && row) {
        setRowError({ row: row.id, symbol, message, suggestions })
        setStatus(last ? { kind: 'done', done: last } : { kind: 'idle' })
      } else setStatus({ kind: 'failed', message, suggestions })
    }
  }

  // The example runs once on the first visit.
  const first = useEffectEvent(() => void run(rows, target, false))
  useEffect(() => {
    if (started.current) return
    started.current = true
    first()
    fetchRepos()
      .then((list) => {
        if (list.length) setRepos(list)
      })
      .catch(() => {
        // Without the list the two usual repos stay; a run says what is missing.
      })
  }, [])

  const switchTo = (key: string) => {
    const next = targetOf(key)
    setTargetKey(key)
    setRowError(null)
    setMissing({})
    setFormError(null)
    setLast(null)
    const example = next.kind === 'demo' ? EXAMPLES[next.id] : undefined
    const nextRows = example ? rowsOf(example) : blankRows()
    setRows(nextRows)
    if (example) void run(nextRows, next, false)
    else setStatus({ kind: 'idle' })
  }

  const update = (id: number, patch: Partial<Row>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))
    if (rowError?.row === id && patch.symbols) setRowError(null)
    if (missing[id] && patch.symbols?.length) setMissing((m) => Object.fromEntries(Object.entries(m).filter(([k]) => Number(k) !== id)))
  }

  const removeRow = (id: number) => {
    setRows((rs) => rs.filter((r) => r.id !== id))
    if (rowError?.row === id) setRowError(null)
  }

  const fix = (err: RowError, replacement: string) => {
    const next = rows.map((r) =>
      r.id === err.row ? { ...r, symbols: r.symbols.includes(replacement) ? r.symbols.filter((s) => s !== err.symbol) : r.symbols.map((s) => (s === err.symbol ? replacement : s)) } : r,
    )
    setRows(next)
    void run(next, target, true)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(rows, target, true)
  }

  const running = status.kind === 'running'
  const shown = status.kind === 'done' ? status.done : null

  return (
    <>
      <Nav />
      <main>
        <Container className="pt-14 pb-24 sm:pt-20 sm:pb-32">
          <h1 className="display max-w-[880px] text-[44px] text-balance sm:text-[64px]">Plan parallel work before any agent starts.</h1>
          <p className="mt-5 max-w-[620px] text-[18px] leading-relaxed text-muted text-pretty">
            Write the tasks you are about to hand out and the symbols each will change. Pre-flight says which can run in parallel and which must coordinate, with the path between them. It is a graph query, not a model call.
          </p>
          <a
            href={sectionHref('graph')}
            className="group mt-5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-text underline decoration-line-strong underline-offset-4 hover:decoration-text"
          >
            Why a graph
            <ArrowRight size={14} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
          </a>

          <div className="mt-10 grid items-start gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <form onSubmit={submit} noValidate className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <label htmlFor="preflight-repo" className="text-[14px] font-semibold text-text">
                  Repo
                </label>
                <div className="relative">
                  <select
                    id="preflight-repo"
                    value={targetKey}
                    onChange={(e) => switchTo(e.target.value)}
                    className="h-9 appearance-none rounded-[8px] bg-surface pr-9 pl-3 text-[14px] font-medium text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2 focus:outline-none focus-visible:shadow-[inset_0_0_0_1px_var(--muted)]"
                  >
                    {workspaces.length ? (
                      <>
                        <optgroup label="Demo repos">
                          {repos.map((r) => (
                            <option key={r.id} value={`demo:${r.id}`}>
                              {r.name}
                            </option>
                          ))}
                        </optgroup>
                        <optgroup label="Your workspaces">
                          {workspaces.map((w) => (
                            <option key={w.id} value={`workspace:${w.id}`}>
                              {w.name}
                            </option>
                          ))}
                        </optgroup>
                      </>
                    ) : (
                      repos.map((r) => (
                        <option key={r.id} value={`demo:${r.id}`}>
                          {r.name}
                        </option>
                      ))
                    )}
                  </select>
                  <CaretDown size={14} weight="bold" className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted" />
                </div>
                {repo && repo.symbols > 0 && <span className="text-[14px] text-muted">{repo.symbols.toLocaleString('en-GB')} symbols in the graph</span>}
              </div>

              <div className="mt-4 rounded-[14px] border border-line bg-surface">
                <div className="flex h-11 items-center justify-between gap-4 border-b border-line px-4">
                  <h2 className="text-[14px] font-semibold text-text">Tasks</h2>
                  <span className="text-[13.5px] text-muted tabular-nums">
                    {rows.length} of {TASKS_MAX}
                  </span>
                </div>
                <ol className="divide-y divide-line">
                  {rows.map((row, i) => {
                    const look = taskLook(i)
                    const err = rowError?.row === row.id ? rowError : null
                    return (
                      <li key={row.id} className="px-4 py-4">
                        <div className="flex items-center gap-3">
                          <TaskMark look={look} className="size-7 rounded-[7px] text-[12.5px]" />
                          <input
                            value={row.name}
                            onChange={(e) => update(row.id, { name: e.target.value })}
                            placeholder={`Task ${look.letter}`}
                            aria-label={`Name of task ${look.letter}`}
                            maxLength={60}
                            autoComplete="off"
                            className="h-9 min-w-0 flex-1 rounded-[8px] bg-transparent px-2 text-[15px] font-medium text-text placeholder:text-faint hover:bg-surface-2 focus:bg-bg focus:shadow-[inset_0_0_0_1px_var(--muted)] focus:outline-none focus-visible:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => removeRow(row.id)}
                            disabled={rows.length <= TASKS_MIN}
                            aria-label={`Remove task ${look.letter}`}
                            className="grid size-8 shrink-0 place-items-center rounded-[7px] text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-30"
                          >
                            <X size={15} weight="bold" />
                          </button>
                        </div>
                        <div className="mt-2.5 sm:pl-10">
                          <SymbolField
                            target={target}
                            symbols={row.symbols}
                            invalid={err?.symbol}
                            label={`Symbols task ${look.letter} will change`}
                            onChange={(symbols) => update(row.id, { symbols })}
                          />
                          {err && (
                            <div className="mt-2" role="alert">
                              <p className="text-[13.5px] text-bad">
                                {err.message}
                                {err.suggestions.length > 0 && <span className="text-muted"> Pick one to run again.</span>}
                              </p>
                              <Fixes suggestions={err.suggestions} onPick={(s) => fix(err, s)} />
                            </div>
                          )}
                          {!err && missing[row.id] && (
                            <p className="mt-2 text-[13.5px] text-bad" role="alert">
                              {missing[row.id]}
                            </p>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ol>
                <div className="border-t border-line px-2 py-2">
                  <button
                    type="button"
                    onClick={() => setRows((rs) => [...rs, ...rowsOf([{ name: '', symbols: [] }])])}
                    disabled={rows.length >= TASKS_MAX}
                    className="inline-flex h-9 items-center gap-2 rounded-[8px] px-2.5 text-[14px] font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-text disabled:pointer-events-none disabled:opacity-40"
                  >
                    <Plus size={15} weight="bold" />
                    Add task
                  </button>
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
                <button
                  type="submit"
                  disabled={running}
                  className="group inline-flex h-11 w-full items-center justify-center gap-2 rounded-[8px] bg-accent px-[18px] text-[15px] font-semibold text-accent-ink transition-[transform,filter] duration-200 ease-out hover:brightness-[1.07] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-60 sm:w-auto"
                >
                  {running ? 'Running' : 'Run pre-flight'}
                  {!running && <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />}
                </button>
                {formError ? (
                  <p className="text-[14px] text-bad" role="alert">
                    {formError}
                  </p>
                ) : (
                  <p className="text-[14px] text-muted">Same tasks, same graph, same answer.</p>
                )}
              </div>
            </form>

            <div ref={resultRef} className="min-w-0 scroll-mt-24 lg:sticky lg:top-24">
              <section className="overflow-hidden rounded-[14px] border border-line bg-surface" aria-label="Pre-flight result">
                <div className="flex h-11 items-center justify-between gap-4 border-b border-line px-4">
                  <h2 className="text-[14px] font-semibold text-text">Plan</h2>
                  <span className="truncate text-[13.5px] text-muted">{targetName}</span>
                </div>
                <div aria-live="polite" aria-busy={running}>
                  {running ? (
                    <ResultSkeleton />
                  ) : status.kind === 'failed' ? (
                    <Placeholder>
                      <p className="font-semibold text-bad">Pre-flight did not run.</p>
                      <p className="mt-1">{status.message}</p>
                      <Fixes suggestions={status.suggestions} className="justify-center" />
                    </Placeholder>
                  ) : shown ? (
                    <Result answer={shown.answer} looks={shown.looks} />
                  ) : (
                    <Placeholder>Give two or more tasks their symbols and run pre-flight. The groups, where tasks meet and the hot spots show here.</Placeholder>
                  )}
                </div>
              </section>
            </div>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  )
}
