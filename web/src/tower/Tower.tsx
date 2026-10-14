import { ArrowClockwise } from '@phosphor-icons/react'
import { useCallback, useEffect, useMemo, type ReactNode } from 'react'
import { Wordmark } from '../ui'
import { clock, httpApi, shortName, type CollisionSummary, type RadarSymbol, type TowerApi } from './api'
import { CollisionPanel, ResolutionSign } from './CollisionPanel'
import { agentLooks, type AgentLook } from './layout'
import { LiveRadar } from './LiveRadar'
import { createMockApi, mockVariant } from './mock'
import { collisionPath, navigate } from './nav'
import { AgentName, Sidebar } from './Sidebar'
import { useLive, type Conn } from './useLive'

const connWord: Record<Conn, { text: string; className: string }> = {
  live: { text: 'Live', className: 'text-ok' },
  reconnecting: { text: 'Reconnecting', className: 'text-muted' },
  offline: { text: 'Offline', className: 'text-bad' },
}

function TopBar({ repo, conn }: { repo?: string; conn: Conn | null }) {
  return (
    <header className="flex h-13 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-3 text-[14px]">
        <a href="/" className="shrink-0 rounded-[6px]" aria-label="Airspace home">
          <Wordmark />
        </a>
        <span className="text-faint" aria-hidden="true">
          /
        </span>
        <span className="font-semibold text-text">Tower</span>
        {repo && (
          <>
            <span className="text-faint" aria-hidden="true">
              /
            </span>
            <span className="truncate text-muted">{repo}</span>
          </>
        )}
      </div>
      {conn && (
        <p className={`shrink-0 text-[13px] font-semibold ${connWord[conn].className}`} aria-live="polite">
          {connWord[conn].text}
        </p>
      )}
    </header>
  )
}

function Commands({ lines }: { lines: string[] }) {
  return (
    <pre className="mt-5 overflow-x-auto rounded-[10px] border border-line bg-surface px-4 py-3.5 text-left font-mono text-[13px] leading-[1.9] text-text">
      {lines.join('\n')}
    </pre>
  )
}

/** Two quiet airspaces, the shape Tower fills once agents fly. */
function EmptyScope() {
  return (
    <svg viewBox="0 0 150 104" className="h-16 w-auto text-line-strong" aria-hidden="true">
      <circle cx="52" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="98" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

function Notice({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-1 items-start justify-center px-5 py-16 sm:items-center sm:py-24">
      <div className="w-full max-w-[440px]">
        <EmptyScope />
        <h1 className="mt-6 text-[20px] leading-snug font-semibold tracking-[-0.015em] text-text text-balance">{title}</h1>
        {children}
      </div>
    </div>
  )
}

function Skeleton() {
  return (
    <div className="flex flex-1 flex-col lg:grid lg:min-h-0 lg:grid-cols-[280px_minmax(0,1fr)]" aria-busy="true" aria-label="Loading Tower">
      <aside className="order-2 border-t border-line bg-surface p-3 lg:order-1 lg:border-t-0 lg:border-r">
        <div className="mx-2.5 mt-1 mb-3 h-3 w-14 rounded bg-surface-2" />
        {[0, 1].map((i) => (
          <div key={i} className="flex items-center gap-3 px-2.5 py-2">
            <div className="size-8 rounded-[7px] bg-surface-2" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-20 rounded bg-surface-2" />
              <div className="h-3 w-14 rounded bg-surface-2" />
            </div>
          </div>
        ))}
        <div className="mx-2.5 mt-7 mb-3 h-3 w-16 rounded bg-surface-2" />
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex gap-3 px-2.5 py-2">
            <div className="h-3 w-12 rounded bg-surface-2" />
            <div className="h-3 flex-1 rounded bg-surface-2" style={{ maxWidth: `${80 - i * 12}%` }} />
          </div>
        ))}
      </aside>
      <main className="order-1 px-4 pt-5 pb-8 sm:px-8 lg:order-2">
        <div className="mx-auto flex h-[22px] max-w-[960px] items-center px-1">
          <div className="h-3 w-12 rounded bg-surface-2" />
        </div>
        <svg viewBox="0 0 760 460" className="mx-auto mt-6 block w-full max-w-[760px] animate-pulse text-line-strong" aria-hidden="true">
          <circle cx="225" cy="230" r="206" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <circle cx="535" cy="230" r="206" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <circle cx="225" cy="230" r="104" fill="none" stroke="currentColor" strokeDasharray="2 6" />
          <circle cx="535" cy="230" r="104" fill="none" stroke="currentColor" strokeDasharray="2 6" />
        </svg>
      </main>
    </div>
  )
}

function CollisionList({ collisions, selected, looks, symbols }: { collisions: CollisionSummary[]; selected: string | null; looks: Record<string, AgentLook>; symbols?: Record<string, RadarSymbol> }) {
  if (!collisions.length) return null
  return (
    <section className="mx-auto mt-6 w-full max-w-[960px]">
      <h2 className="px-1 pb-2 text-[12.5px] font-semibold text-muted">Collisions</h2>
      <ul className="overflow-hidden rounded-[10px] border border-line bg-surface">
        {collisions.map((c, i) => (
          <li key={c.id} className={i > 0 ? 'border-t border-line' : ''}>
            <button
              type="button"
              onClick={() => navigate(collisionPath(c.id))}
              aria-current={selected === c.id ? 'true' : undefined}
              className={`flex w-full items-center gap-3 px-4 py-3 text-left text-[13.5px] transition-colors hover:bg-surface-2 ${selected === c.id ? 'bg-surface-2' : ''}`}
            >
              <ResolutionSign resolution={c.resolution} />
              <span className="min-w-0 flex-1 truncate text-muted">
                <AgentName id={c.held_agent} look={looks[c.held_agent]} /> was held at <span className="font-mono text-text">{shortName(c.symbol, symbols)}</span>
                <span className="hidden sm:inline">
                  , which <AgentName id={c.owner_agent} look={looks[c.owner_agent]} /> {c.kind === 'contract' ? 'is changing' : 'claims'}
                </span>
              </span>
              <span className="shrink-0 font-mono text-[11.5px] text-faint">{clock(c.at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function Tower({ collisionId }: { collisionId: string | null }) {
  const api: TowerApi = useMemo(() => {
    const v = mockVariant(window.location.search)
    return v ? createMockApi(v) : httpApi
  }, [])
  const live = useLive(api)
  const { state, radar, events, phase } = live

  useEffect(() => {
    document.title = 'Tower | Airspace'
  }, [])

  const looks = useMemo(
    () => agentLooks([...(state?.agents.map((a) => a.id) ?? []), ...(radar?.agents.map((a) => a.id) ?? []), ...events.map((e) => e.agent)]),
    [state, radar, events],
  )

  const openCollision = useCallback((id: string) => navigate(collisionPath(id)), [])
  const close = useCallback(() => navigate('/tower'), [])

  useEffect(() => {
    if (!collisionId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [collisionId, close])

  const empty = phase === 'ready' && !!state && state.agents.length === 0 && (radar?.agents.length ?? 0) === 0 && !collisionId

  let body: ReactNode
  if (phase === 'loading') body = <Skeleton />
  else if (phase === 'error')
    body = (
      <Notice title="Tower cannot reach the Airspace server on port 8787.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">Start it from the repo:</p>
        <Commands lines={['airspace serve --root .']} />
        <button
          type="button"
          onClick={live.retry}
          className="mt-5 inline-flex h-9 items-center gap-2 rounded-[8px] px-3 text-[13.5px] font-semibold text-text shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:bg-surface-2"
        >
          <ArrowClockwise size={15} weight="bold" /> Try again
        </button>
      </Notice>
    )
  else if (empty)
    body = (
      <Notice title="No agents are flying yet.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">Index the repo and install the hooks:</p>
        <Commands lines={['airspace index --root .', 'airspace install-hooks --root .']} />
        <p className="mt-5 text-[15px] leading-relaxed text-muted">Start two Claude Code sessions in the repo.</p>
      </Notice>
    )
  else {
    const agents = state?.agents ?? []
    const holds = agents.filter((a) => a.held).length
    body = (
      <div className="flex flex-1 flex-col lg:grid lg:min-h-0 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="order-2 border-t border-line bg-surface lg:order-1 lg:min-h-0 lg:overflow-y-auto lg:border-t-0 lg:border-r">
          <Sidebar agents={agents} events={events} looks={looks} api={api} onChanged={live.refresh} />
        </aside>
        <main className={`order-1 flex flex-col lg:order-2 lg:min-h-0 lg:overflow-y-auto ${collisionId ? 'xl:grid xl:grid-cols-[minmax(0,1fr)_380px] xl:overflow-hidden' : ''}`}>
          <section className="min-w-0 px-4 pt-5 pb-8 sm:px-8 xl:min-h-0 xl:overflow-y-auto" aria-label="Radar">
            <div className="mx-auto flex w-full max-w-[960px] items-baseline justify-between gap-4 px-1">
              <h1 className="text-[15px] font-semibold text-text">Radar</h1>
              <p className="text-[13px] text-muted">
                {agents.length === 1 ? '1 agent' : `${agents.length} agents`}
                {holds > 0 && <span className="text-accent">{`, ${holds === 1 ? '1 hold' : `${holds} holds`}`}</span>}
              </p>
            </div>
            <div className="mt-4 sm:mt-6">{radar && radar.agents.length > 0 ? <LiveRadar radar={radar} state={state} looks={looks} onOpenCollision={openCollision} /> : <p className="py-16 text-center text-[14px] text-muted">No airspace to draw yet.</p>}</div>
            <CollisionList collisions={state?.collisions ?? []} selected={collisionId} looks={looks} symbols={radar?.symbols} />
          </section>
          {collisionId && (
            <section className="min-w-0 border-y border-line bg-surface xl:min-h-0 xl:overflow-y-auto xl:border-y-0 xl:border-l" aria-label="Collision">
              <CollisionPanel key={collisionId} id={collisionId} api={api} tick={live.tick} agents={agents} looks={looks} symbols={radar?.symbols} onClose={close} onChanged={live.refresh} />
            </section>
          )}
        </main>
      </div>
    )
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-text lg:h-dvh">
      <TopBar repo={state?.repo} conn={phase === 'loading' ? null : live.conn} />
      {body}
    </div>
  )
}
