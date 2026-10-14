import { ArrowClockwise, Pause, Play } from '@phosphor-icons/react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { connectCommands } from '../account/api'
import { LogoMark, Wordmark } from '../ui'
import { clock, createHttpApi, httpApi, shortName, type CollisionSummary, type RadarSymbol, type TowerApi } from './api'
import { CollisionPanel, ResolutionSign } from './CollisionPanel'
import { agentLooks, type AgentLook } from './layout'
import { LiveRadar } from './LiveRadar'
import { MemorySection } from './Memory'
import { createMockApi, mockReplay, mockVariant } from './mock'
import { collisionPath, navigate, workspacePath } from './nav'
import { duration, fetchMode, fetchReplay } from './replay'
import { CommandLines } from './CommandLines'
import { AgentName, Sidebar } from './Sidebar'
import { useLive, type Conn, type Live } from './useLive'
import { useRecentMemory } from './useMemory'
import { useReplay, type Player } from './useReplay'

const connWord: Record<Conn | 'replay', { text: string; className: string }> = {
  live: { text: 'Live', className: 'text-ok' },
  reconnecting: { text: 'Reconnecting', className: 'text-muted' },
  offline: { text: 'Offline', className: 'text-bad' },
  replay: { text: 'Replay', className: 'text-muted' },
}

/** A hosted workspace's Tower: its own graph, always live. */
export type TowerWorkspace = { id: string; name: string }

export function TopBar({ repo, conn, workspace }: { repo?: string; conn: Conn | 'replay' | null; workspace?: TowerWorkspace }) {
  const crumb = workspace ? workspace.name : repo
  return (
    <header className="flex h-13 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-3 text-[14px]">
        <a href="/" className="shrink-0 rounded-[6px]" aria-label="Airspace home">
          {workspace ? (
            <>
              <Wordmark className="max-sm:hidden" />
              <LogoMark className="h-[19px] w-auto text-text sm:hidden" />
            </>
          ) : (
            <Wordmark />
          )}
        </a>
        <span className="text-faint" aria-hidden="true">
          /
        </span>
        <span className="font-semibold text-text">Tower</span>
        {crumb && (
          <>
            <span className="text-faint" aria-hidden="true">
              /
            </span>
            <span className={`truncate ${workspace ? 'font-medium text-text' : 'text-muted'}`}>{crumb}</span>
          </>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-4">
        {conn && (
          <p className={`text-[13px] font-semibold ${connWord[conn].className}`} aria-live="polite">
            {connWord[conn].text}
          </p>
        )}
        {workspace && (
          <a href="/app" className="text-[13.5px] font-medium text-muted transition-colors hover:text-text">
            Workspaces
          </a>
        )}
      </div>
    </header>
  )
}

export function Commands({ lines, wrap = false }: { lines: string[]; wrap?: boolean }) {
  if (wrap)
    return (
      <pre className="mt-5 rounded-[10px] border border-line bg-surface px-4 py-3.5 text-left font-mono text-[13px] leading-[1.9] whitespace-normal text-text">
        <CommandLines lines={lines} />
      </pre>
    )
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

export function Notice({ title, children }: { title: string; children?: ReactNode }) {
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

export function Skeleton() {
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

function CollisionList({
  collisions,
  selected,
  looks,
  symbols,
  base,
}: {
  collisions: CollisionSummary[]
  selected: string | null
  looks: Record<string, AgentLook>
  symbols?: Record<string, RadarSymbol>
  base: string
}) {
  if (!collisions.length) return null
  return (
    <section className="mx-auto mt-6 w-full max-w-[960px]">
      <h2 className="px-1 pb-2 text-[12.5px] font-semibold text-muted">Collisions</h2>
      <ul className="overflow-hidden rounded-[10px] border border-line bg-surface">
        {collisions.map((c, i) => (
          <li key={c.id} className={i > 0 ? 'border-t border-line' : ''}>
            <button
              type="button"
              onClick={() => navigate(collisionPath(c.id, base))}
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

function ReplayBar({ player, sample }: { player: Player; sample: boolean }) {
  const { index, count, playing, elapsed, total, toggle, seek } = player
  const progress = count > 1 ? (index / (count - 1)) * 100 : 100
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-line bg-surface px-4 py-2 sm:flex-nowrap sm:px-5">
      <p className="shrink-0 text-[13.5px] font-semibold text-text">{sample ? 'Replay of a sample run' : 'Replay of a real run'}</p>
      <div className="flex min-w-0 basis-full items-center gap-3 sm:flex-1 sm:basis-auto">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? 'Pause the replay' : 'Play the replay'}
          className="grid size-8 shrink-0 place-items-center rounded-[7px] text-text shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:bg-surface-2"
        >
          {playing ? <Pause size={14} weight="fill" /> : <Play size={14} weight="fill" />}
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(0, count - 1)}
          step={1}
          value={index}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="Replay position"
          aria-valuetext={`Event ${index + 1} of ${count}, ${duration(elapsed)} into the run`}
          className="scrub min-w-0 flex-1"
          style={{ '--p': `${progress}%` } as CSSProperties}
        />
        <span className="shrink-0 text-[13px] text-muted tabular-nums">
          {duration(elapsed)} <span className="text-faint">/ {duration(total)}</span>
        </span>
      </div>
      <p className="hidden shrink-0 text-[13px] text-faint xl:block">Controls are off while a recording plays.</p>
    </div>
  )
}

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-5 inline-flex h-9 items-center gap-2 rounded-[8px] px-3 text-[13.5px] font-semibold text-text shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:bg-surface-2"
    >
      <ArrowClockwise size={15} weight="bold" /> Try again
    </button>
  )
}

type ViewProps = {
  live: Live
  api: TowerApi
  collisionId: string | null
  /** A recording: actions are off and the replay bar sits under the top bar. */
  replay?: { player: Player; sample: boolean }
  workspace?: TowerWorkspace
}

function TowerView({ live, api, collisionId, replay, workspace }: ViewProps) {
  const { state, radar, events, phase } = live
  const readOnly = !!replay

  const looks = useMemo(
    () => agentLooks([...(state?.agents.map((a) => a.id) ?? []), ...(radar?.agents.map((a) => a.id) ?? []), ...events.filter((e) => e.agent !== 'Tower').map((e) => e.agent)]),
    [state, radar, events],
  )

  const memory = useRecentMemory(api, live.tick)

  const base = workspace ? workspacePath(workspace.id) : '/tower'
  const openCollision = useCallback((id: string) => navigate(collisionPath(id, base)), [base])
  const close = useCallback(() => navigate(base), [base])

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
  else if (phase === 'error' && replay)
    body = (
      <Notice title="Tower could not load the replay.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">The server has no recording, or it did not answer.</p>
        <RetryButton onClick={live.retry} />
      </Notice>
    )
  else if (phase === 'error' && workspace)
    body = (
      <Notice title="Tower could not load this workspace.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">The server did not answer, or your session ended. Tower keeps trying.</p>
        <RetryButton onClick={live.retry} />
      </Notice>
    )
  else if (phase === 'error')
    body = (
      <Notice title="Tower cannot reach the Airspace server on port 8787.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">Start it from the repo:</p>
        <Commands lines={['airspace serve --root .']} />
        <RetryButton onClick={live.retry} />
      </Notice>
    )
  else if (replay && replay.player.count === 0) body = <Notice title="This recording has no events yet." />
  else if (empty && workspace)
    body = (
      <Notice title="No agents are flying yet.">
        <p className="mt-2 text-[15px] leading-relaxed text-muted">Connect your repo to this workspace with its key, and install the hooks:</p>
        <Commands lines={connectCommands('ask_...')} wrap />
        <p className="mt-5 text-[15px] leading-relaxed text-muted">
          Use the key you got when you made the workspace. Lost it? Make a new one on the{' '}
          <a href="/app" className="font-medium text-text underline decoration-line-strong underline-offset-4 transition-colors hover:decoration-text">
            workspaces page
          </a>
          . Then start two Claude Code sessions in the repo.
        </p>
      </Notice>
    )
  else if (empty && !replay)
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
          <Sidebar agents={agents} events={events} looks={looks} api={api} onChanged={live.refresh} readOnly={readOnly}>
            <MemorySection api={api} memory={memory} looks={looks} symbols={radar?.symbols} readOnly={readOnly} />
          </Sidebar>
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
            <CollisionList collisions={state?.collisions ?? []} selected={collisionId} looks={looks} symbols={radar?.symbols} base={base} />
          </section>
          {collisionId && (
            <section className="min-w-0 border-y border-line bg-surface xl:min-h-0 xl:overflow-y-auto xl:border-y-0 xl:border-l" aria-label="Collision">
              <CollisionPanel key={collisionId} id={collisionId} api={api} tick={live.tick} agents={agents} looks={looks} symbols={radar?.symbols} onClose={close} onChanged={live.refresh} onNoted={memory.reload} readOnly={readOnly} />
            </section>
          )}
        </main>
      </div>
    )
  }

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-text lg:h-dvh">
      <TopBar repo={state?.repo} conn={phase === 'loading' ? null : replay ? 'replay' : live.conn} workspace={workspace} />
      {replay && phase === 'ready' && replay.player.count > 0 && <ReplayBar player={replay.player} sample={replay.sample} />}
      {body}
    </div>
  )
}

function LiveTower({ api, collisionId, workspace }: { api: TowerApi; collisionId: string | null; workspace?: TowerWorkspace }) {
  const live = useLive(api)
  return <TowerView live={live} api={api} collisionId={collisionId} workspace={workspace} />
}

/** Tower for a hosted workspace, on /api/w/<id>. Always live: workspaces have no recording. */
export function WorkspaceTowerView({ workspace, collisionId }: { workspace: TowerWorkspace; collisionId: string | null }) {
  const api = useMemo(() => createHttpApi(`/api/w/${encodeURIComponent(workspace.id)}`), [workspace.id])
  useEffect(() => {
    document.title = `${workspace.name} | Tower | Airspace`
  }, [workspace.name])
  return <LiveTower key={workspace.id} api={api} collisionId={collisionId} workspace={workspace} />
}

const MODE_POLL_MS = 15000
const loadSample = async () => mockReplay()

function ReplayTower({ sample, collisionId, onLive }: { sample: boolean; collisionId: string | null; onLive?: () => void }) {
  const { live, player, api } = useReplay(sample ? loadSample : fetchReplay)

  // A deployed Tower plays the recording while nothing flies, and goes live once an agent does.
  useEffect(() => {
    if (!onLive) return
    const t = window.setInterval(() => {
      fetchMode()
        .then((m) => m === 'live' && onLive())
        .catch(() => {})
    }, MODE_POLL_MS)
    return () => window.clearInterval(t)
  }, [onLive])

  return <TowerView live={live} api={api} collisionId={collisionId} replay={{ player, sample }} />
}

type Mode = { kind: 'live'; api: TowerApi } | { kind: 'replay'; sample: boolean; forced: boolean } | { kind: 'deciding' }

function firstMode(search: string): Mode {
  const variant = mockVariant(search)
  if (variant === 'replay') return { kind: 'replay', sample: true, forced: true }
  if (variant) return { kind: 'live', api: createMockApi(variant) }
  if (new URLSearchParams(search).get('replay') === '1') return { kind: 'replay', sample: false, forced: true }
  return { kind: 'deciding' }
}

export default function Tower({ collisionId }: { collisionId: string | null }) {
  const [mode, setMode] = useState<Mode>(() => firstMode(window.location.search))

  useEffect(() => {
    document.title = 'Tower | Airspace'
  }, [])

  // Ask the server whether to play its recording. A server without /api/mode, or none at all, means live.
  useEffect(() => {
    if (mode.kind !== 'deciding') return
    let alive = true
    fetchMode()
      .then((m) => alive && setMode(m === 'replay' ? { kind: 'replay', sample: false, forced: false } : { kind: 'live', api: httpApi }))
      .catch(() => alive && setMode({ kind: 'live', api: httpApi }))
    return () => {
      alive = false
    }
  }, [mode.kind])

  const goLive = useCallback(() => setMode({ kind: 'live', api: httpApi }), [])

  if (mode.kind === 'deciding')
    return (
      <div className="flex min-h-dvh flex-col bg-bg text-text lg:h-dvh">
        <TopBar conn={null} />
        <Skeleton />
      </div>
    )
  if (mode.kind === 'replay') return <ReplayTower sample={mode.sample} collisionId={collisionId} onLive={mode.forced ? undefined : goLive} />
  return <LiveTower api={mode.api} collisionId={collisionId} />
}
