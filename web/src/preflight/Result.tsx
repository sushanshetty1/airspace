import { Fragment, type ReactNode } from 'react'
import type { PairKind, PreflightAnswer, TaskHistory } from './api'
import type { TaskLook } from './looks'
import { Qualname } from './SymbolField'

export function TaskMark({ look, className = 'size-5 text-[11px] rounded-[5px]' }: { look: TaskLook; className?: string }) {
  return (
    <span className={`grid shrink-0 place-items-center font-bold text-ink ${className}`} style={{ background: look.color }} aria-hidden="true">
      {look.letter}
    </span>
  )
}

function TaskChip({ name, look }: { name: string; look: TaskLook }) {
  return (
    <span className="inline-flex h-8 max-w-full items-center gap-2 rounded-[8px] bg-surface px-2 text-[14px] font-medium text-text shadow-[0_0_0_1px_var(--line)]">
      <TaskMark look={look} />
      <span className="truncate">{name}</span>
    </span>
  )
}

const KIND_ORDER: Record<PairKind, number> = { same_symbol: 0, calls: 1, shared_dependents: 2 }

function kindWords(kind: PairKind, shared: number) {
  if (kind === 'same_symbol') return 'change the same symbol'
  if (kind === 'calls') return 'one calls the other'
  return shared === 1 ? 'share 1 dependent' : `share ${shared} dependents`
}

/** Qualnames joined by arrows; each arrow stays with the name after it, so a line never starts with one. */
function Path({ path }: { path: string[] }) {
  return (
    <p className="text-[13px] leading-[1.7]">
      {path.map((q, i) => (
        <Fragment key={`${q}-${i}`}>
          {i > 0 && (
            <span className="text-faint" aria-label="calls">
              {' → '}
            </span>
          )}
          <Qualname q={q} />
        </Fragment>
      ))}
    </p>
  )
}

function Heading({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div className="mb-3">
      <h3 className="text-[13.5px] font-semibold text-text">{children}</h3>
      {note && <p className="mt-0.5 text-[13.5px] text-muted">{note}</p>}
    </div>
  )
}

const count = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.round(n) : 0)
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** "From earlier sessions: 3 collisions, 2 notes", naming only what there is; null when there is neither. */
function historyLine(h: TaskHistory | null | undefined) {
  if (!h || typeof h !== 'object') return null
  const parts = [
    [count(h.collisions), 'collision', 'collisions'],
    [count(h.notes), 'note', 'notes'],
  ] as const
  const said = parts.filter(([n]) => n > 0).map(([n, one, many]) => plural(n, one, many))
  return said.length ? `From earlier sessions: ${said.join(', ')}` : null
}

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))

export function Result({ answer, looks }: { answer: PreflightAnswer; looks: Record<string, TaskLook> }) {
  const look = (name: string) => looks[name] ?? { color: 'var(--muted)', letter: '?' }
  const coordinate = answer.groups.filter((g) => g.coordinate && g.tasks.length > 1)
  const parallel = answer.groups.filter((g) => !(g.coordinate && g.tasks.length > 1)).flatMap((g) => g.tasks)
  const pairs = [...answer.pairs].sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind])
  const maxCone = Math.max(1, ...answer.tasks.map((t) => t.cone))

  return (
    <div className="divide-y divide-line">
      <div className="px-5 py-5 sm:px-6">
        <p className="max-w-[60ch] text-[17px] leading-relaxed font-medium text-text text-pretty">{answer.summary}</p>
        <div className={`mt-5 grid gap-2 ${coordinate.length && parallel.length ? 'sm:grid-cols-2' : ''}`}>
          {coordinate.length > 0 && (
            <div className="rounded-[10px] bg-accent-soft p-3">
              <p className="text-[13px] font-semibold text-accent">
                Must coordinate{coordinate.length > 1 ? `, in ${coordinate.length} groups` : ''}
              </p>
              <div className="mt-2.5 space-y-2">
                {coordinate.map((g) => (
                  // Each group is its own box: tasks in different boxes do not wait for each other.
                  <div key={g.tasks.join('\n')} className="flex flex-wrap gap-1.5 rounded-[8px] p-1.5 shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--accent)_30%,transparent)]">
                    {g.tasks.map((t) => (
                      <TaskChip key={t} name={t} look={look(t)} />
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
          {parallel.length > 0 && (
            <div className="rounded-[10px] bg-ok-soft p-3">
              <p className="text-[13px] font-semibold text-ok">Can run in parallel</p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {parallel.map((t) => (
                  <TaskChip key={t} name={t} look={look(t)} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="px-5 py-5 sm:px-6">
        <Heading>Where tasks meet</Heading>
        {pairs.length ? (
          <ul className="space-y-4">
            {pairs.map((p) => {
              const extra = p.kind === 'shared_dependents' ? p.shared - p.symbols.length : 0
              return (
                <li key={`${p.a}\n${p.b}`}>
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[14px]">
                    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <TaskMark look={look(p.a)} />
                      <span className="font-medium text-text">{p.a}</span>
                      <span className="text-muted">and</span>
                      <TaskMark look={look(p.b)} />
                      <span className="font-medium text-text">{p.b}</span>
                    </span>
                    <span className={`text-[13.5px] ${p.kind === 'shared_dependents' ? 'text-muted' : 'font-medium text-accent'}`}>{kindWords(p.kind, p.shared)}</span>
                  </div>
                  <div className="mt-1.5 rounded-[8px] bg-surface-2 px-3 py-2">
                    {p.path.length > 1 ? (
                      <Path path={p.path} />
                    ) : (
                      <p className="text-[13px] leading-[1.7]">
                        {p.symbols.map((s, i) => (
                          <Fragment key={s}>
                            {i > 0 && <span className="text-faint">, </span>}
                            <Qualname q={s} />
                          </Fragment>
                        ))}
                        {extra > 0 && <span className="text-muted"> and {extra} more</span>}
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-[14.5px] text-muted">No task reaches another within two hops.</p>
        )}
      </div>

      <div className="grid sm:grid-cols-2 sm:divide-x sm:divide-line max-sm:divide-y max-sm:divide-line">
        <div className="px-5 py-5 sm:px-6">
          <Heading note="Callers, tests and subclasses within two hops.">Dependents per task</Heading>
          <ul className="space-y-2.5">
            {answer.tasks.map((t) => {
              const history = historyLine(t.history)
              return (
                <li key={t.name} title={t.cone_sample?.length ? t.cone_sample.join('\n') : undefined}>
                  <div className="flex items-baseline justify-between gap-3 text-[14px]">
                    <span className="flex min-w-0 items-center gap-2 self-center">
                      <TaskMark look={look(t.name)} />
                      <span className="truncate text-text">{t.name}</span>
                    </span>
                    <span className="shrink-0 font-medium text-text tabular-nums">{t.cone}</span>
                  </div>
                  <div className="mt-1.5 h-1 rounded-full bg-surface-2">
                    <div className="h-full rounded-full" style={{ width: `${Math.max(2, (t.cone / maxCone) * 100)}%`, background: look(t.name).color }} />
                  </div>
                  {history && <p className="mt-1.5 text-[13px] text-muted">{history}</p>}
                </li>
              )
            })}
          </ul>
        </div>
        <div className="px-5 py-5 sm:px-6">
          <Heading note="Symbols that many paths between these tasks run through.">Hot spots</Heading>
          {answer.hot.length ? (
            <ul className="space-y-2">
              {answer.hot.map((h) => (
                <li key={h.qualname} className="flex items-baseline justify-between gap-4 text-[13px]">
                  <Qualname q={h.qualname} className="min-w-0" />
                  <span className="shrink-0 text-[13.5px] text-muted tabular-nums" title="Betweenness">
                    {fmt(h.betweenness)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[14px] text-muted">No symbol stands between these tasks.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function Bone({ className }: { className: string }) {
  return <span className={`block animate-pulse rounded-[6px] bg-surface-2 ${className}`} />
}

/** The result's shape while the graph answers. */
export function ResultSkeleton() {
  return (
    <div className="divide-y divide-line" aria-hidden="true">
      <div className="px-5 py-5 sm:px-6">
        <Bone className="h-5 w-[85%]" />
        <Bone className="mt-2.5 h-5 w-[55%]" />
        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          {[0, 1].map((i) => (
            <div key={i} className="rounded-[10px] bg-surface-2/60 p-3">
              <Bone className="h-3.5 w-28" />
              <div className="mt-3 flex gap-1.5">
                <Bone className="h-8 w-32" />
                <Bone className="h-8 w-24" />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="space-y-4 px-5 py-5 sm:px-6">
        <Bone className="h-4 w-32" />
        {[0, 1].map((i) => (
          <div key={i}>
            <Bone className="h-4 w-[60%]" />
            <Bone className="mt-2 h-9 w-full" />
          </div>
        ))}
      </div>
      <div className="grid sm:grid-cols-2 sm:divide-x sm:divide-line max-sm:divide-y max-sm:divide-line">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-3 px-5 py-5 sm:px-6">
            <Bone className="h-4 w-36" />
            <Bone className="h-4 w-full" />
            <Bone className="h-4 w-[80%]" />
            <Bone className="h-4 w-[90%]" />
          </div>
        ))}
      </div>
    </div>
  )
}
