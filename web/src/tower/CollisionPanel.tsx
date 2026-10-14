import { ChatCircleText, LockOpen, PauseCircle, PlayCircle, X } from '@phosphor-icons/react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Sign } from '../ui'
import { Action } from './Action'
import { clock, fixFor, MESSAGE_MAX, shortName, type AgentState, type CollisionDetail, type MemoryItem, type RadarSymbol, type Resolution, type TowerApi } from './api'
import { AddNote, FixNote } from './Memory'
import { AgentName } from './Sidebar'
import type { AgentLook } from './layout'

type Feedback = { tone: 'ok' | 'bad' | 'muted'; text: string } | null

export function ResolutionSign({ resolution }: { resolution: Resolution }) {
  if (resolution === 'held') return <Sign kind="HOLD">Hold</Sign>
  if (resolution === 'released') return <Sign kind="BRIEFED">Released</Sign>
  return <Sign kind="CLEARED">Resolved</Sign>
}

/** Splits "name(a, b=1)" into its parameters, to mark the ones the other signature lacks. */
function params(sig: string) {
  const open = sig.indexOf('(')
  const close = sig.lastIndexOf(')')
  if (open < 0 || close < open) return null
  return { head: sig.slice(0, open + 1), list: sig.slice(open + 1, close).split(',').map((p) => p.trim()).filter(Boolean), tail: sig.slice(close) }
}

/** The held agent's signature, with the parameters the new one no longer has marked. */
function Signature({ sig, other, mark }: { sig: string; other: string | null | undefined; mark: boolean }) {
  const mine = params(sig)
  const theirs = other ? params(other) : null
  if (!mark || !mine || !theirs) return <>{sig}</>
  return (
    <>
      {mine.head}
      {mine.list.map((p, i) => (
        <span key={i}>
          {i > 0 && ', '}
          {theirs.list.includes(p) ? p : <span className="bg-accent px-1 whitespace-nowrap text-accent-ink">{p}</span>}
        </span>
      ))}
      {mine.tail}
    </>
  )
}

function Loc({ q, symbols }: { q: string; symbols?: Record<string, RadarSymbol> }) {
  return (
    <span title={q}>
      <Sign kind="LOCATION">{shortName(q, symbols)}</Sign>
    </span>
  )
}

export function CollisionPanel({
  id,
  api,
  tick,
  agents,
  looks,
  symbols,
  onClose,
  onChanged,
  onNoted,
  readOnly = false,
}: {
  id: string
  api: TowerApi
  tick: number
  agents: AgentState[]
  looks: Record<string, AgentLook>
  symbols?: Record<string, RadarSymbol>
  onClose: () => void
  onChanged: () => void
  /** A note was saved here, so the memory list can refetch. */
  onNoted?: () => void
  /** A recording: the actions are replaced by one line saying why. */
  readOnly?: boolean
}) {
  const [detail, setDetail] = useState<{ id: string; data: CollisionDetail | null } | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [text, setText] = useState('')
  const [textError, setTextError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'message' | 'release' | 'pause' | null>(null)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const fieldId = useId()
  const root = useRef<HTMLDivElement>(null)

  // Below the three column layout the panel sits under the radar; bring it into view.
  useEffect(() => {
    if (window.matchMedia('(max-width: 1279px)').matches) root.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [id])

  useEffect(() => {
    let alive = true
    api
      .collision(id)
      .then((data) => {
        if (!alive) return
        setDetail({ id, data })
        setLoadError(false)
      })
      .catch(() => alive && setLoadError(true))
    return () => {
      alive = false
    }
  }, [api, id, tick])

  const c = detail?.id === id ? detail.data : undefined

  // A resolved collision's fix, from what the graph remembers about its symbol.
  const [fix, setFix] = useState<{ id: string; item: MemoryItem | null } | null>(null)
  const resolved = c?.resolution === 'resolved'
  // Primitives, so the lookup runs again on a new tick or another collision, not on every refetched object.
  const rId = resolved ? c.id : null
  const rSymbol = resolved ? c.symbol : ''
  const rAt = resolved ? c.at : 0
  const rHeld = resolved ? c.held_agent : ''
  useEffect(() => {
    if (!rId) return
    let alive = true
    const find = async () => {
      const about = await api.memory([rSymbol]).catch(() => null)
      const items = about ?? (await api.recentMemory(50).catch(() => null)) ?? []
      return fixFor({ id: rId, symbol: rSymbol, at: rAt, held_agent: rHeld }, items)
    }
    find().then((item) => alive && setFix({ id: rId, item }))
    return () => {
      alive = false
    }
  }, [api, rId, rSymbol, rAt, rHeld, tick])
  const fixNote = rId && fix?.id === rId ? fix.item : null

  const header = (right?: ReactNode) => (
    <div className="flex h-12 items-center justify-between gap-3 border-b border-line px-5">
      <div className="flex min-w-0 items-center gap-2.5 text-[14px]">
        <span className="font-semibold text-text">Collision</span>
        <span className="truncate font-mono text-[12.5px] text-faint">{id}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {right}
        <button type="button" onClick={onClose} aria-label="Close the collision" className="-mr-1.5 grid size-8 place-items-center rounded-[6px] text-muted transition-colors hover:bg-surface-2 hover:text-text">
          <X size={16} weight="bold" />
        </button>
      </div>
    </div>
  )

  if (c === undefined) {
    return (
      <div ref={root}>
        {header()}
        <div className="px-5 py-5">
          {loadError ? (
            <p className="text-[14px] text-muted">Tower could not load this collision. It tries again with the next update.</p>
          ) : (
            <div className="space-y-3" aria-hidden="true">
              <div className="h-3 w-28 rounded bg-surface-2" />
              <div className="h-4 w-full rounded bg-surface-2" />
              <div className="h-4 w-4/5 rounded bg-surface-2" />
            </div>
          )}
        </div>
      </div>
    )
  }

  if (c === null) {
    return (
      <div ref={root}>
        {header()}
        <p className="px-5 py-5 text-[14px] text-muted">This collision is not on record any more.</p>
      </div>
    )
  }

  const owner = agents.find((a) => a.id === c.owner_agent)
  const ownerPaused = owner?.paused ?? false
  const isCall = !!c.caller && c.caller !== c.symbol
  const hasSigs = c.kind === 'contract' && !!c.new_sig && !!c.old_sig
  const held = c.resolution === 'held'
  const trimmed = text.trim()

  const run = async (kind: 'message' | 'release' | 'pause', work: () => Promise<Feedback>) => {
    setBusy(kind)
    setFeedback(null)
    try {
      setFeedback(await work())
      onChanged()
    } catch (e) {
      const why = e instanceof Error && e.message ? ` ${e.message.replace(/\.?$/, '.')}` : ''
      setFeedback({ tone: 'bad', text: `${kind === 'message' ? 'The message was not sent.' : kind === 'release' ? 'The hold was not released.' : `${c.owner_agent} was not ${ownerPaused ? 'resumed' : 'paused'}.`}${why}` })
    } finally {
      setBusy(null)
    }
  }

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!trimmed) return setTextError('Write a message first.')
    if (text.length > MESSAGE_MAX) return setTextError(`Messages can be up to ${MESSAGE_MAX} characters.`)
    setTextError(null)
    run('message', async () => {
      await api.message(c.held_agent, text)
      setText('')
      return { tone: 'ok', text: `Sent. ${c.held_agent} reads it on its next edit.` }
    })
  }

  const release = () =>
    run('release', async () => {
      const ok = await api.release(c.id)
      return ok ? { tone: 'ok', text: `Released. ${c.held_agent} can retry its edit.` } : { tone: 'muted', text: 'This hold was already lifted.' }
    })

  const togglePause = () =>
    run('pause', async () => {
      if (ownerPaused) {
        await api.resume(c.owner_agent)
        return { tone: 'ok', text: `${c.owner_agent} is resumed.` }
      }
      await api.pause(c.owner_agent)
      return { tone: 'ok', text: `${c.owner_agent} is paused. Its edits are held until you resume it.` }
    })

  const over = text.length > MESSAGE_MAX

  return (
    <div ref={root}>
      {header(<ResolutionSign resolution={c.resolution} />)}
      <div className="divide-y divide-line">
        <section className="px-5 py-5">
          <h3 className="text-[13px] font-semibold text-muted">Why it was held</h3>
          <p className="mt-2.5 text-[15px] leading-[2.1] text-muted">
            <AgentName id={c.held_agent} look={looks[c.held_agent]} className="font-semibold" />
            's edit {isCall ? <>makes <Loc q={c.caller!} symbols={symbols} /> call </> : <>touches </>}
            <span className="whitespace-nowrap">
              <Loc q={c.symbol} symbols={symbols} />,
            </span>{' '}
            which <AgentName id={c.owner_agent} look={looks[c.owner_agent]} className="font-semibold" /> {c.kind === 'contract' ? 'is changing' : 'has claimed'}.
          </p>
          {c.path.length > 2 && (
            <p className="mt-2 font-mono text-[12.5px] leading-relaxed text-muted [overflow-wrap:anywhere]">
              {c.path.map((q) => shortName(q, symbols)).join(' → ')}
            </p>
          )}
          <p className="mt-2 text-[13px] text-faint">Held at {clock(c.at)}</p>
        </section>

        {hasSigs && (
          <dl className="grid grid-cols-[minmax(96px,auto)_minmax(0,1fr)] gap-x-4 gap-y-3 px-5 py-5 font-mono text-[12.5px]">
            <dt style={{ color: looks[c.owner_agent]?.color }}>{c.owner_agent} has</dt>
            <dd className="break-words text-text">
              <Signature sig={c.new_sig!} other={c.old_sig} mark={false} />
            </dd>
            <dt style={{ color: looks[c.held_agent]?.color }}>{c.held_agent} wrote</dt>
            <dd className="break-words text-text">
              <Signature sig={c.old_sig!} other={c.new_sig} mark={held} />
            </dd>
          </dl>
        )}

        {fixNote && <FixNote fix={fixNote} symbols={symbols} />}

        {readOnly ? (
          <p className="px-5 py-5 text-[13.5px] leading-relaxed text-muted">
            {held ? `${c.held_agent} is held at this point of the run. ` : c.resolution === 'released' ? 'The hold was released from Tower. ' : `${c.held_agent} cleared this collision. `}
            Message, release and pause are off while a recording plays.
          </p>
        ) : (
          <>
            <form className="px-5 py-5" onSubmit={send} noValidate>
              <label htmlFor={fieldId} className="text-[13px] font-semibold text-muted">
                Message <span className="font-mono font-medium">{c.held_agent}</span>
              </label>
              <textarea
                id={fieldId}
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  if (textError) setTextError(null)
                }}
                rows={3}
                placeholder={hasSigs ? `Use the new signature: ${c.new_sig}` : 'What should it do instead?'}
                aria-invalid={!!textError || over}
                aria-describedby={`${fieldId}-hint`}
                className={`mt-2 block w-full resize-y rounded-[8px] bg-bg px-3 py-2.5 text-[14px] leading-relaxed text-text placeholder:text-faint focus:outline-none focus-visible:outline-none ${
                  textError || over ? 'shadow-[inset_0_0_0_1px_var(--bad)]' : 'shadow-[inset_0_0_0_1px_var(--line-strong)] focus:shadow-[inset_0_0_0_1px_var(--muted)]'
                }`}
              />
              <div className="mt-3 flex items-center gap-3">
                <p id={`${fieldId}-hint`} className="min-w-0 flex-1 text-[12.5px] leading-snug text-bad" aria-live="polite">
                  {textError ?? (over ? `Messages can be up to ${MESSAGE_MAX} characters.` : '')}
                </p>
                <span className={`shrink-0 font-mono text-[11.5px] ${over ? 'text-bad' : 'text-faint'}`}>
                  {text.length}/{MESSAGE_MAX}
                </span>
                <Action type="submit" primary disabled={busy !== null}>
                  <ChatCircleText size={16} weight="bold" /> {busy === 'message' ? 'Sending' : 'Send'}
                </Action>
              </div>
            </form>

            <section className="px-5 py-5">
              <div className="flex flex-wrap gap-2">
                <Action onClick={release} disabled={!held || busy !== null}>
                  <LockOpen size={16} weight="bold" /> {busy === 'release' ? 'Releasing' : 'Release hold'}
                </Action>
                <Action onClick={togglePause} disabled={busy !== null || !owner}>
                  {ownerPaused ? <PlayCircle size={16} weight="bold" /> : <PauseCircle size={16} weight="bold" />}
                  {busy === 'pause' ? (ownerPaused ? 'Resuming' : 'Pausing') : `${ownerPaused ? 'Resume' : 'Pause'} ${c.owner_agent}`}
                </Action>
              </div>
              <p className={`mt-3 min-h-[20px] text-[13.5px] leading-relaxed ${feedback?.tone === 'bad' ? 'text-bad' : feedback?.tone === 'ok' ? 'text-text' : 'text-muted'}`} aria-live="polite">
                {feedback?.text ?? (held ? `Send ${c.held_agent} the fix, or release the hold yourself.` : c.resolution === 'released' ? 'The hold was released from Tower.' : `${c.held_agent} cleared this collision.`)}
              </p>
            </section>

            <section className="px-5 py-4">
              <AddNote key={c.symbol} api={api} symbol={c.symbol} symbols={symbols} label={`Add a note about ${shortName(c.symbol, symbols)}`} onSaved={onNoted} />
            </section>
          </>
        )}
      </div>
    </div>
  )
}
