import { Plus } from '@phosphor-icons/react'
import { Fragment, useEffect, useId, useState, type FormEvent } from 'react'
import { Action } from './Action'
import { ago, NOTE_MAX, shortName, type MemoryItem, type RadarSymbol, type TowerApi } from './api'
import type { AgentLook } from './layout'
import { AgentName } from './Sidebar'
import type { Memory } from './useMemory'

/** Calls such as slugify(post.title, unicode=True), one level of nested parentheses deep. */
const CALL = /[A-Za-z_][\w.]*\((?:[^()]|\([^()]*\))*\)/g

/** Memory text with the calls in it set in mono. */
export function MemoryText({ text }: { text: string }) {
  const parts: { code: boolean; s: string }[] = []
  let last = 0
  for (const m of text.matchAll(CALL)) {
    if (m.index > last) parts.push({ code: false, s: text.slice(last, m.index) })
    parts.push({ code: true, s: m[0] })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ code: false, s: text.slice(last) })
  return (
    <>
      {parts.map((p, i) =>
        p.code ? (
          <span key={i} className="font-mono text-[0.92em]">
            {p.s}
          </span>
        ) : (
          <Fragment key={i}>{p.s}</Fragment>
        ),
      )}
    </>
  )
}

const kindWord: Record<MemoryItem['kind'], string> = { note: 'Note', fix: 'Fix', contract: 'Change' }

/** "Fix from agent-b", with Tower and Airspace as plain words and agents in their colour. */
function Byline({ item, looks }: { item: MemoryItem; looks: Record<string, AgentLook> }) {
  const plain = !item.agent || item.agent === 'Tower' || item.agent === 'Airspace'
  return (
    <p className="mt-1 text-[12.5px] text-faint">
      <span className={item.kind === 'fix' ? 'font-medium text-ok' : ''}>{kindWord[item.kind] ?? 'Note'}</span> from{' '}
      {plain ? <span className="text-muted">{item.agent || 'Tower'}</span> : <AgentName id={item.agent} look={looks[item.agent]} />}
    </p>
  )
}

/** Re-render once a minute so relative times stay true. */
function useMinute() {
  const [, setN] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setN((n) => n + 1), 60000)
    return () => window.clearInterval(t)
  }, [])
}

const fieldClass = (bad: boolean) =>
  `block w-full rounded-[8px] bg-bg px-3 text-[14px] text-text placeholder:text-faint focus:outline-none focus-visible:outline-none ${
    bad ? 'shadow-[inset_0_0_0_1px_var(--bad)]' : 'shadow-[inset_0_0_0_1px_var(--line-strong)] focus:shadow-[inset_0_0_0_1px_var(--muted)]'
  }`

/** Symbol and text, posted to /notes. The server's refusal shows under the fields. */
export function NoteForm({
  api,
  initialSymbol = '',
  symbols,
  onSaved,
  onCancel,
}: {
  api: TowerApi
  initialSymbol?: string
  symbols?: Record<string, RadarSymbol>
  onSaved: (symbol: string) => void
  onCancel: () => void
}) {
  const [symbol, setSymbol] = useState(initialSymbol)
  const [text, setText] = useState('')
  const [error, setError] = useState<{ field: 'symbol' | 'text' | null; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const id = useId()
  const over = text.length > NOTE_MAX
  const known = Object.keys(symbols ?? {}).sort()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const s = symbol.trim()
    const t = text.trim()
    if (!s) return setError({ field: 'symbol', text: 'Name the symbol the note is about.' })
    if (!t) return setError({ field: 'text', text: 'Write the note first.' })
    if (over) return setError({ field: 'text', text: `Notes can be up to ${NOTE_MAX} characters.` })
    setError(null)
    setBusy(true)
    try {
      await api.addNote([s], t)
      setText('')
      onSaved(s)
    } catch (err) {
      const text = err instanceof Error && err.message ? err.message.replace(/\.?$/, '.') : 'The note was not saved.'
      // "No symbol named X." and "X matches several symbols." are about the symbol field.
      setError({ field: /^No symbol named |matches several symbols/.test(text) ? 'symbol' : null, text })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3">
      <div>
        <label htmlFor={`${id}-symbol`} className="text-[13px] font-semibold text-muted">
          Symbol
        </label>
        <input
          id={`${id}-symbol`}
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value)
            if (error) setError(null)
          }}
          list={known.length ? `${id}-known` : undefined}
          placeholder="utils.text.slugify"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={error?.field === 'symbol'}
          className={`mt-1.5 h-9 font-mono text-[13px] ${fieldClass(error?.field === 'symbol')}`}
        />
        {known.length > 0 && (
          <datalist id={`${id}-known`}>
            {known.map((q) => (
              <option key={q} value={q} />
            ))}
          </datalist>
        )}
      </div>
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <label htmlFor={`${id}-text`} className="text-[13px] font-semibold text-muted">
            Note
          </label>
          <span className={`font-mono text-[11.5px] ${over ? 'text-bad' : 'text-faint'}`}>
            {text.length}/{NOTE_MAX}
          </span>
        </div>
        <textarea
          id={`${id}-text`}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            if (error) setError(null)
          }}
          rows={3}
          placeholder="What should the next agent here know?"
          aria-invalid={error?.field === 'text' || over}
          aria-describedby={`${id}-error`}
          className={`mt-1.5 resize-y py-2.5 leading-relaxed ${fieldClass(error?.field === 'text' || over)}`}
        />
      </div>
      <p id={`${id}-error`} className="text-[12.5px] leading-snug text-bad empty:hidden" role="alert">
        {error?.text ?? (over ? `Notes can be up to ${NOTE_MAX} characters.` : '')}
      </p>
      <div className="flex flex-wrap gap-2">
        <Action type="submit" primary disabled={busy}>
          {busy ? 'Saving' : 'Save note'}
        </Action>
        <Action onClick={onCancel} disabled={busy}>
          Cancel
        </Action>
      </div>
    </form>
  )
}

/** A quiet "Add a note" button that opens the form in place, and says where the note went once saved. */
export function AddNote({ api, symbol, symbols, label = 'Add a note', onSaved }: { api: TowerApi; symbol?: string; symbols?: Record<string, RadarSymbol>; label?: string; onSaved?: () => void }) {
  const [open, setOpen] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  if (open)
    return (
      <NoteForm
        api={api}
        initialSymbol={symbol}
        symbols={symbols}
        onCancel={() => setOpen(false)}
        onSaved={(s) => {
          setOpen(false)
          setSaved(s)
          onSaved?.()
        }}
      />
    )
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          setSaved(null)
          setOpen(true)
        }}
        className="-ml-1.5 inline-flex h-8 items-center gap-1.5 rounded-[6px] px-1.5 text-[13px] font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-text"
      >
        <Plus size={14} weight="bold" /> {label}
      </button>
      {saved && (
        <p className="mt-1 text-[13px] leading-relaxed text-text" aria-live="polite">
          Saved. Agents that touch <span className="font-mono text-[12.5px]">{shortName(saved, symbols)}</span> hear it once.
        </p>
      )}
    </div>
  )
}

/** The sidebar's Memory section: the newest notes and fixes, and a way to add one. */
export function MemorySection({ api, memory, looks, symbols, readOnly }: { api: TowerApi; memory: Memory; looks: Record<string, AgentLook>; symbols?: Record<string, RadarSymbol>; readOnly: boolean }) {
  useMinute()
  const { items, failed, reload } = memory
  // A server without memory has nothing to show here.
  if (items === null) return null

  return (
    <section aria-label="Memory">
      <h2 className="px-2.5 pt-6 pb-2 text-[12.5px] font-semibold text-muted">Memory</h2>
      {!readOnly && (
        <div className="px-2.5 pb-2">
          <AddNote api={api} symbols={symbols} onSaved={reload} />
        </div>
      )}
      {items === undefined ? (
        failed ? (
          <p className="px-2.5 py-1.5 text-[13px] text-muted">Memory did not load. Tower tries again with the next update.</p>
        ) : (
          <div className="space-y-2 px-2.5 py-1.5" aria-hidden="true">
            <div className="h-3 w-20 rounded bg-surface-2" />
            <div className="h-3 w-full rounded bg-surface-2" />
          </div>
        )
      ) : items.length === 0 ? (
        <p className="px-2.5 py-1.5 text-[13px] leading-relaxed text-faint">Fixes and notes left on the code. Every later agent that touches it hears them once.</p>
      ) : (
        <ol className="space-y-0.5">
          {items.map((m) => (
            <li key={m.id} className="px-2.5 py-2">
              <p className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate font-mono text-[12.5px] font-medium text-text" title={m.symbol}>
                  {shortName(m.symbol, symbols)}
                </span>
                <span className="shrink-0 text-[12px] text-faint">{ago(m.at)}</span>
              </p>
              <p className="mt-1 line-clamp-4 text-[13px] leading-snug text-muted [overflow-wrap:anywhere]" title={m.text.length > 160 ? m.text : undefined}>
                <MemoryText text={m.text} />
              </p>
              <Byline item={m} looks={looks} />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

/** In the collision panel: the fix Airspace wrote when this collision cleared. */
export function FixNote({ fix, symbols }: { fix: MemoryItem; symbols?: Record<string, RadarSymbol> }) {
  return (
    <section className="px-5 py-5">
      <h3 className="text-[13px] font-semibold text-muted">Written to memory</h3>
      <p className="mt-2.5 text-[14.5px] leading-relaxed text-text [overflow-wrap:anywhere]">
        <MemoryText text={fix.text} />
      </p>
      <p className="mt-2 text-[13px] text-faint">
        Later agents that touch <span className="font-mono text-[12.5px]">{shortName(fix.symbol, symbols)}</span> hear this before they write the call.
      </p>
    </section>
  )
}
