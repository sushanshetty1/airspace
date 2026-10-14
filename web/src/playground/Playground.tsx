import { ArrowRight } from '@phosphor-icons/react'
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from 'react'
import { ScopeView } from '../radar/Scope'
import { Footer } from '../sections/Footer'
import { Nav } from '../sections/Nav'
import { shortName, type RadarData } from '../tower/api'
import { agentLooks, layoutRadar } from '../tower/layout'
import { AgentName } from '../tower/Sidebar'
import { Container, Frame, Sign, signLabel } from '../ui'

type Fields = { symbol: string; new_signature: string; caller: string; call: string }
type FieldName = keyof Fields

type CheckResult = {
  verdict: 'hold' | 'cleared'
  reason: string
  path: string[]
  callee: string
  old_signature: string
  /** Whether this server's engine checks the call's arguments against the new signature. */
  checks_arguments: boolean
  radar: RadarData
}

const examples: { label: string; fields: Fields }[] = [
  {
    label: 'The story',
    fields: { symbol: 'utils.text.slugify', new_signature: 'slugify(value, *, unicode=False)', caller: 'blog.views.render_post', call: 'slugify(post.title, True)' },
  },
  {
    label: 'Compatible keyword call',
    fields: { symbol: 'utils.text.slugify', new_signature: 'slugify(value, *, unicode=False)', caller: 'blog.views.render_post', call: 'slugify(post.title, unicode=True)' },
  },
  {
    label: 'Renamed method',
    fields: { symbol: 'blog.models.Post.get_absolute_url', new_signature: 'url(self)', caller: 'blog.feeds.LatestPosts.item_description', call: 'post.get_absolute_url()' },
  },
  {
    label: 'Constructor with a new argument',
    fields: { symbol: 'blog.models.Post.__init__', new_signature: '__init__(self, title, body, author)', caller: 'blog.views.post_list', call: 'Post(title, body)' },
  },
]

// The fixture repo the server checks against: a small blog app with tags and a feed.
const SIGNATURES: Record<string, string> = {
  'utils.text.slugify': 'slugify(value, allow_unicode=False)',
  'utils.text.truncate_words': 'truncate_words(text, count=30)',
  'blog.models.Post': 'Post()',
  'blog.models.Post.__init__': '__init__(self, title, body)',
  'blog.models.Post.save': 'save(self)',
  'blog.models.Post.get_absolute_url': 'get_absolute_url(self)',
  'blog.views.render_post': 'render_post(post)',
  'blog.views.post_list': 'post_list(posts)',
  'blog.feeds.LatestPosts': 'LatestPosts()',
  'blog.feeds.LatestPosts.item_description': 'item_description(self, post)',
  'tags.models.Tag': 'Tag()',
  'tags.models.Tag.__init__': '__init__(self, name)',
  'tags.models.Tag.save': 'save(self)',
  'tags.views.tag_create': 'tag_create(name)',
}

const same = (a: Fields, b: Fields) => (Object.keys(a) as FieldName[]).every((k) => a[k].trim() === b[k].trim())

/** Which field a server message is about, so it can sit under that field. */
function fieldOf(message: string): FieldName | null {
  if (message.startsWith('The new signature')) return 'new_signature'
  if (message.startsWith('The symbol')) return 'symbol'
  if (message.startsWith('The caller')) return 'caller'
  if (message.startsWith('The call') || / is not a function, method or class| matches several symbols/.test(message)) return 'call'
  return null
}

type Status = { kind: 'idle' } | { kind: 'checking' } | { kind: 'done'; result: CheckResult; fields: Fields } | { kind: 'failed'; message: string }

async function runCheck(f: Fields): Promise<CheckResult> {
  let res: Response
  try {
    res = await fetch('/api/playground/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change: { symbol: f.symbol.trim(), new_signature: f.new_signature.trim() }, edit: { caller: f.caller.trim(), call: f.call.trim() } }),
    })
  } catch {
    throw new CheckError(0, 'The playground server did not answer. Try again in a moment.')
  }
  const data = (await res.json().catch(() => null)) as (CheckResult & { error?: unknown; detail?: unknown }) | null
  if (!res.ok || !data) {
    const message = typeof data?.error === 'string' ? data.error : res.status === 429 ? 'Too many checks from this address. Try again in a minute.' : `The server answered ${res.status}.`
    throw new CheckError(res.status, message)
  }
  return data
}

class CheckError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function Field({
  label,
  name,
  value,
  error,
  hint,
  list,
  onChange,
}: {
  label: string
  name: FieldName
  value: string
  error?: string | null
  hint?: ReactNode
  list?: string
  onChange: (name: FieldName, value: string) => void
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="text-[13.5px] font-semibold text-text">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(name, e.target.value)}
        list={list}
        spellCheck={false}
        autoCapitalize="off"
        autoComplete="off"
        aria-invalid={!!error}
        aria-describedby={`${id}-note`}
        className={`mt-2 block h-10 w-full rounded-[8px] bg-bg px-3 font-mono text-[13.5px] text-text placeholder:text-faint focus:outline-none focus-visible:outline-none ${
          error ? 'shadow-[inset_0_0_0_1px_var(--bad)]' : 'shadow-[inset_0_0_0_1px_var(--line-strong)] focus:shadow-[inset_0_0_0_1px_var(--muted)]'
        }`}
      />
      <p id={`${id}-note`} className={`mt-1.5 min-h-[18px] text-[12.5px] leading-snug ${error ? 'text-bad' : 'text-faint'}`} aria-live="polite">
        {error ?? hint}
      </p>
    </div>
  )
}

const PHONE = '(max-width: 639px)'

function usePhone() {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(PHONE)
      mq.addEventListener('change', cb)
      return () => mq.removeEventListener('change', cb)
    },
    () => window.matchMedia(PHONE).matches,
  )
}

/** The scratch graph's airspaces after the check. A cleared call into the change shows as a cleared lens. */
function ResultScope({ result, fields }: { result: CheckResult; fields: Fields }) {
  const compact = usePhone()
  const { radar, model } = useMemo(() => {
    let r = result.radar
    const [caller, target] = result.path
    if (result.verdict === 'cleared' && !r.collision && target === fields.symbol.trim() && r.agents.length === 2) {
      r = { ...r, collision: { id: 'playground', symbol: target, caller, held_agent: 'agent-b', owner_agent: 'agent-a', resolution: 'resolved' } }
    }
    const looks = agentLooks(r.agents.map((a) => a.id))
    return { radar: r, model: layoutRadar(r, looks, new Set(), { compact }).model }
  }, [result, fields, compact])
  if (!radar.agents.length) return null
  const label = `agent-a's airspace around ${shortName(fields.symbol.trim(), radar.symbols)} and agent-b's around ${shortName(fields.caller.trim(), radar.symbols)}. The edit is ${result.verdict === 'hold' ? 'held' : 'cleared'}.`
  return <ScopeView model={model} label={label} className="mx-auto" style={{ maxWidth: Math.round(model.view.w * 0.9) }} />
}

function Verdict({ result, fields }: { result: CheckResult; fields: Fields }) {
  const hold = result.verdict === 'hold'
  const path = result.path.map((q) => shortName(q, result.radar.symbols)).join(' → ')
  const keywordCall = /\w=/.test(fields.call)
  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)] lg:items-center">
      <div className="pb-2 lg:pb-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-5 pt-6 sm:px-6">
          <Sign kind={hold ? 'HOLD' : 'CLEARED'} className="h-10 rounded-[8px] px-4 text-[19px]">
            {hold ? signLabel.HOLD : signLabel.CLEARED}
          </Sign>
          <p className="font-mono text-[13.5px] text-text [overflow-wrap:anywhere]" title={result.path.join(' → ')}>
            {path}
          </p>
        </div>
        <div className="px-5 pt-5 sm:px-6">
          <h3 className="text-[13px] font-semibold text-muted">{hold ? 'What agent-b reads in its deny reason' : 'Why'}</h3>
          <p className="mt-2 max-w-[68ch] text-[15px] leading-relaxed text-text">{result.reason}</p>
          {hold && !result.checks_arguments && keywordCall && (
            <p className="mt-3 max-w-[68ch] text-[13.5px] leading-relaxed text-muted">
              The engine on this server holds every new call into a changing contract until the caller is briefed. It does not check the arguments yet.
            </p>
          )}
        </div>
      </div>
      <div className="px-3 pt-4 pb-5 sm:px-6 lg:py-6">
        <ResultScope result={result} fields={fields} />
      </div>
    </div>
  )
}

function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[320px] flex-col items-center justify-center px-6 py-14 text-center">
      <svg viewBox="0 0 150 104" className="h-14 w-auto text-line-strong" aria-hidden="true">
        <circle cx="52" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="98" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <div className="mt-5 max-w-[42ch] text-[14.5px] leading-relaxed text-muted">{children}</div>
    </div>
  )
}

export default function Playground() {
  const [fields, setFields] = useState<Fields>(examples[0].fields)
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({})
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [last, setLast] = useState<{ result: CheckResult; fields: Fields } | null>(null)
  const listId = useId()
  const resultRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.title = 'Playground | Airspace'
  }, [])

  const change = (name: FieldName, value: string) => {
    setFields((f) => ({ ...f, [name]: value }))
    if (errors[name]) setErrors((e) => ({ ...e, [name]: undefined }))
  }

  const pick = (f: Fields) => {
    setFields(f)
    setErrors({})
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const missing: Partial<Record<FieldName, string>> = {}
    for (const k of Object.keys(fields) as FieldName[]) if (!fields[k].trim()) missing[k] = 'Required.'
    if (Object.keys(missing).length) return setErrors(missing)
    setErrors({})
    setStatus({ kind: 'checking' })
    const sent = { ...fields }
    try {
      const result = await runCheck(sent)
      setLast({ result, fields: sent })
      setStatus({ kind: 'done', result, fields: sent })
      const box = resultRef.current?.getBoundingClientRect()
      if (box && box.top > window.innerHeight * 0.6) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'The check failed.'
      const field = err instanceof CheckError && err.status === 422 ? fieldOf(message) : null
      if (field) {
        setErrors({ [field]: message })
        setStatus(last ? { kind: 'done', ...last } : { kind: 'idle' })
      } else setStatus({ kind: 'failed', message })
    }
  }

  const checking = status.kind === 'checking'
  const shown = status.kind === 'done' ? status : checking && last ? { kind: 'done' as const, ...last } : null
  const current = (q: string) => SIGNATURES[q.trim()]

  return (
    <>
      <Nav />
      <main>
        <Container className="pt-14 pb-24 sm:pt-20 sm:pb-32">
          <h1 className="display max-w-[880px] text-[44px] text-balance sm:text-[64px]">Try the clearance check.</h1>
          <p className="mt-5 max-w-[600px] text-[18px] leading-relaxed text-muted text-pretty">
            Change a function as agent-a, write a call to it as agent-b, and the real Airspace engine checks the call on the code graph of a small blog app.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-2" role="group" aria-label="Examples">
            {examples.map((ex) => {
              const on = same(ex.fields, fields)
              return (
                <button
                  key={ex.label}
                  type="button"
                  onClick={() => pick(ex.fields)}
                  aria-pressed={on}
                  className={`h-9 rounded-full px-4 text-[14px] font-medium transition-colors ${on ? 'bg-text text-bg' : 'text-muted shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2 hover:text-text'}`}
                >
                  {ex.label}
                </button>
              )
            })}
          </div>

          <div className="mt-6">
            <form onSubmit={submit} noValidate>
              <datalist id={listId}>
                {Object.keys(SIGNATURES).map((q) => (
                  <option key={q} value={q} />
                ))}
              </datalist>
              <div className="grid gap-4 md:grid-cols-2">
                <Frame
                  title={
                    <>
                      <AgentName id="agent-a" look={{ color: 'var(--agent-a)', soft: '', letter: 'A' }} className="font-medium" />
                      <span className="text-muted">changes a signature</span>
                    </>
                  }
                >
                  <div className="space-y-2 px-4 pt-4 pb-2">
                    <Field
                      label="Symbol"
                      name="symbol"
                      value={fields.symbol}
                      error={errors.symbol}
                      list={listId}
                      onChange={change}
                      hint={
                        current(fields.symbol) ? (
                          <>
                            Now <span className="font-mono">{current(fields.symbol)}</span>
                          </>
                        ) : (
                          'A qualname in the blog app.'
                        )
                      }
                    />
                    <Field
                      label="New signature"
                      name="new_signature"
                      value={fields.new_signature}
                      error={errors.new_signature}
                      onChange={change}
                      hint={
                        <>
                          Read as <span className="font-mono">def &lt;signature&gt;: pass</span>
                        </>
                      }
                    />
                  </div>
                </Frame>
                <Frame
                  title={
                    <>
                      <AgentName id="agent-b" look={{ color: 'var(--agent-b)', soft: '', letter: 'B' }} className="font-medium" />
                      <span className="text-muted">writes a call</span>
                    </>
                  }
                >
                  <div className="space-y-2 px-4 pt-4 pb-2">
                    <Field
                      label="In"
                      name="caller"
                      value={fields.caller}
                      error={errors.caller}
                      list={listId}
                      onChange={change}
                      hint={
                        current(fields.caller) ? (
                          <>
                            Now <span className="font-mono">{current(fields.caller)}</span>
                          </>
                        ) : (
                          'A qualname in the blog app.'
                        )
                      }
                    />
                    <Field label="Call" name="call" value={fields.call} error={errors.call} onChange={change} hint="One call expression" />
                  </div>
                </Frame>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
                <button
                  type="submit"
                  disabled={checking}
                  className="group inline-flex h-11 w-full items-center justify-center gap-2 rounded-[8px] bg-accent px-[18px] text-[15px] font-semibold text-accent-ink transition-[transform,filter] duration-200 ease-out hover:brightness-[1.07] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-60 sm:w-auto"
                >
                  {checking ? 'Checking' : 'Check'}
                  {!checking && <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />}
                </button>
                <p className="text-[14px] text-muted">agent-a records its change first, then agent-b's edit goes through clearance.</p>
              </div>
            </form>

            <div ref={resultRef} className="mt-8 scroll-mt-24">
              <Frame title={<span className="font-semibold text-text">Clearance</span>} className="min-w-0">
                <div aria-live="polite" aria-busy={checking} className={`transition-opacity duration-200 ${checking ? 'opacity-50' : ''}`}>
                  {status.kind === 'failed' ? (
                    <Placeholder>
                      <p className="font-semibold text-bad">The check did not run.</p>
                      <p className="mt-1">{status.message}</p>
                    </Placeholder>
                  ) : shown ? (
                    <Verdict result={shown.result} fields={shown.fields} />
                  ) : checking ? (
                    <Placeholder>Indexing the blog app into a scratch graph and running the check.</Placeholder>
                  ) : (
                    <Placeholder>The verdict, the reason and both airspaces show here.</Placeholder>
                  )}
                </div>
              </Frame>
            </div>
          </div>
        </Container>
      </main>
      <Footer />
    </>
  )
}
