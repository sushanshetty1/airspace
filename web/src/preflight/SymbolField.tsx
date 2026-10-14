import { X } from '@phosphor-icons/react'
import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { searchSymbols, type SymbolHit, type Target } from './api'

export const SYMBOLS_MAX = 10

/** Breaks a qualname after its dots first, and inside a name only when one name is wider than the line. */
function Dotted({ text }: { text: string }) {
  const parts = text.split('.')
  return parts.map((p, i) => (
    <Fragment key={i}>
      {p}
      {i < parts.length - 1 && (
        <>
          .<wbr />
        </>
      )}
    </Fragment>
  ))
}

/** flask.helpers.get_flashed_messages, with the module quieter than the name. */
export function Qualname({ q, className = '', tone = 'text-text' }: { q: string; className?: string; tone?: string }) {
  const cut = q.lastIndexOf('.')
  return (
    <span className={`font-mono [overflow-wrap:break-word] ${className}`}>
      {cut > 0 && (
        <span className="text-muted">
          <Dotted text={q.slice(0, cut + 1)} />
        </span>
      )}
      <span className={tone}>{cut > 0 ? q.slice(cut + 1) : q}</span>
    </span>
  )
}

/** Symbols per repo and query, as the server answered them; null when the search failed. */
type Results = Record<string, SymbolHit[] | null>

/** The symbols of one task: chips, then a search-as-you-type input over the repo's graph. */
export function SymbolField({
  target,
  symbols,
  invalid,
  label,
  onChange,
}: {
  target: Target
  symbols: string[]
  /** The symbol the server could not resolve, shown in red. */
  invalid?: string | null
  label: string
  onChange: (symbols: string[]) => void
}) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<Results>({})
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const listId = useId()
  const q = text.trim()
  const key = `${target.kind}:${target.id}\n${q}`
  const known = !q || key in results

  useEffect(() => {
    if (known) return
    const ctl = new AbortController()
    const t = window.setTimeout(async () => {
      try {
        const hits = await searchSymbols(target, q, ctl.signal)
        setResults((r) => ({ ...r, [key]: hits }))
      } catch {
        if (!ctl.signal.aborted) setResults((r) => ({ ...r, [key]: null }))
      }
    }, 140)
    return () => {
      window.clearTimeout(t)
      ctl.abort()
    }
  }, [q, key, known, target])

  const answer = results[key]
  const hits = (answer ?? []).filter((h) => !symbols.includes(h.qualname))
  const full = symbols.length >= SYMBOLS_MAX
  const showList = open && !!q && !full
  const current = Math.min(active, Math.max(hits.length - 1, 0))

  const add = (qualname: string) => {
    const s = qualname.trim()
    if (s && !symbols.includes(s) && !full) onChange([...symbols, s])
    setText('')
    setActive(0)
    input.current?.focus()
  }

  const remove = (s: string) => {
    onChange(symbols.filter((x) => x !== s))
    input.current?.focus()
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && hits.length) {
      e.preventDefault()
      setOpen(true)
      setActive((current + 1) % hits.length)
    } else if (e.key === 'ArrowUp' && hits.length) {
      e.preventDefault()
      setOpen(true)
      setActive((current - 1 + hits.length) % hits.length)
    } else if (e.key === 'Enter') {
      // Enter adds the highlighted symbol, or the text as typed: the server also resolves short names.
      if (!q) return
      e.preventDefault()
      add(showList && hits[current] ? hits[current].qualname : q)
    } else if (e.key === 'Escape' && showList) {
      e.preventDefault()
      setOpen(false)
    } else if (e.key === 'Backspace' && !text && symbols.length) {
      onChange(symbols.slice(0, -1))
    }
  }

  return (
    <div className="relative">
      <div
        onClick={() => input.current?.focus()}
        className={`flex min-h-10 flex-wrap items-center gap-1.5 rounded-[8px] bg-bg p-1.5 ${
          invalid && symbols.includes(invalid) ? 'shadow-[inset_0_0_0_1px_var(--bad)]' : 'shadow-[inset_0_0_0_1px_var(--line-strong)] focus-within:shadow-[inset_0_0_0_1px_var(--muted)]'
        }`}
      >
        {symbols.map((s) => {
          const bad = s === invalid
          return (
            <span key={s} className={`inline-flex min-h-7 max-w-full items-center gap-0.5 rounded-[6px] py-0.5 pr-0.5 pl-2 text-[12.5px] ${bad ? 'bg-bad-soft' : 'bg-surface-2'}`}>
              <Qualname q={s} tone={bad ? 'text-bad' : 'text-text'} />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  remove(s)
                }}
                aria-label={`Remove ${s}`}
                className="grid size-6 shrink-0 place-items-center rounded-[5px] text-muted transition-colors hover:bg-line hover:text-text"
              >
                <X size={12} weight="bold" />
              </button>
            </span>
          )
        })}
        <input
          ref={input}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setActive(0)
            setOpen(true)
          }}
          onKeyDown={onKey}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          disabled={full}
          placeholder={full ? `${SYMBOLS_MAX} symbols at most` : symbols.length ? 'Add a symbol' : 'Search symbols'}
          aria-label={label}
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && hits[current] ? `${listId}-${current}` : undefined}
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          className="h-7 min-w-[8rem] flex-1 bg-transparent px-1.5 font-mono text-[13px] text-text placeholder:font-sans placeholder:text-[14px] placeholder:text-faint focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed"
        />
      </div>

      {showList && (
        <div className="absolute inset-x-0 top-full z-20 mt-1.5 overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_12px_32px_rgb(0_0_0/0.18)]">
          <ul id={listId} role="listbox" aria-label={`Symbols matching ${q}`} className="max-h-[288px] overflow-y-auto p-1 empty:hidden">
            {hits.map((h, i) => (
              <li
                key={h.qualname}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === current}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => add(h.qualname)}
                className={`flex cursor-pointer items-baseline justify-between gap-3 rounded-[6px] px-2.5 py-2 text-[13px] ${i === current ? 'bg-surface-2' : ''}`}
              >
                <Qualname q={h.qualname} className="min-w-0" />
                <span className="shrink-0 text-[12.5px] text-muted">{h.kind}</span>
              </li>
            ))}
          </ul>
          {known && !hits.length && (
            <p className="px-3.5 py-3 text-[13px] text-muted">
              {answer === null ? 'Search is not answering. Press Enter to add the name as typed.' : 'No symbol matches. Press Enter to add it as typed.'}
            </p>
          )}
          {!known && !hits.length && <p className="px-3.5 py-3 text-[13px] text-faint">Searching</p>}
        </div>
      )}
    </div>
  )
}
