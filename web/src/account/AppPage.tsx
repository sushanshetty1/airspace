import { ArrowClockwise, ArrowRight, Check, Copy, X } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Nav } from '../sections/Nav'
import { ApiError } from '../tower/api'
import { CommandLines } from '../tower/CommandLines'
import { workspacePath } from '../tower/nav'
import { ButtonLink, Container } from '../ui'
import { connectCommands, createWorkspace, deleteWorkspace, NAME_MAX, refreshMe, rotateKey, shortDate, useMe, WHAT_IS_SENT, WORKSPACE_LIMIT, type Workspace } from './api'
import { SignInButton } from './SignIn'

const ease = [0.22, 1, 0.36, 1] as const

/** A failed action: a lapsed session sends the page back to the sign-in prompt. */
function failure(e: unknown, fallback: string) {
  if (e instanceof ApiError && e.status === 401) void refreshMe()
  return e instanceof Error && e.message ? e.message : fallback
}

type Tone = 'primary' | 'secondary' | 'quiet' | 'danger'

const tones: Record<Tone, string> = {
  primary: 'bg-accent text-accent-ink hover:brightness-[1.07]',
  secondary: 'text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2',
  quiet: 'text-muted hover:bg-surface-2 hover:text-text',
  danger: 'text-bad shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-bad-soft',
}

const buttonClass = (tone: Tone, size: 'sm' | 'md' = 'sm') =>
  `group inline-flex items-center justify-center gap-2 rounded-[8px] font-semibold ${size === 'sm' ? 'h-9 px-3 text-[13.5px]' : 'h-10 px-4 text-[14px]'} whitespace-nowrap transition-[transform,opacity,background-color,color,filter] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 ${tones[tone]}`

function Button({
  onClick,
  disabled,
  tone = 'secondary',
  size = 'sm',
  type = 'button',
  className = '',
  children,
}: {
  onClick?: () => void
  disabled?: boolean
  tone?: Tone
  size?: 'sm' | 'md'
  type?: 'button' | 'submit'
  className?: string
  children: ReactNode
}) {
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${buttonClass(tone, size)} ${className}`}>
      {children}
    </button>
  )
}

/** Code to copy: the key, or the commands that use it. */
function CodeBlock({ lines, label }: { lines: string[]; label: string }) {
  const text = lines.join('\n')
  const [copied, setCopied] = useState(false)
  const timer = useRef(0)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 1600)
    } catch {
      // No clipboard access; the text is selectable.
    }
  }

  return (
    <div className="relative mt-2.5 rounded-[10px] border border-line bg-bg">
      <pre className="px-4 py-3 pr-12 font-mono text-[13px] leading-[1.8] whitespace-normal text-text">
        <CommandLines lines={lines} />
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? 'Copied' : `Copy ${label}`}
        className="absolute top-2 right-2 grid size-8 place-items-center rounded-[7px] text-muted transition-colors hover:bg-surface-2 hover:text-text"
      >
        {copied ? <Check size={16} weight="bold" className="text-ok" /> : <Copy size={16} weight="bold" />}
      </button>
    </div>
  )
}

type Reveal = { workspace: string; key: string; fresh: boolean }

/** The key, once, with the two commands that use it. */
function KeyReveal({ reveal, onDone }: { reveal: Reveal; onDone: () => void }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [reveal.key])

  return (
    <motion.section
      ref={ref}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, ease }}
      className="mt-8 scroll-mt-24 rounded-[14px] border border-line-strong bg-surface p-5 sm:p-6"
      aria-label={`Key for ${reveal.workspace}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-text [overflow-wrap:anywhere]">{reveal.fresh ? `${reveal.workspace} is ready` : `New key for ${reveal.workspace}`}</h2>
          <p className="mt-1 text-[14.5px] text-muted">Copy the key now. This is the only time it is shown.</p>
        </div>
        <button type="button" onClick={onDone} aria-label="Hide the key" className="-mt-1 -mr-1 grid size-8 shrink-0 place-items-center rounded-[7px] text-muted transition-colors hover:bg-surface-2 hover:text-text">
          <X size={16} weight="bold" />
        </button>
      </div>

      <CodeBlock lines={[reveal.key]} label="the key" />

      <p className="mt-6 text-[14.5px] font-medium text-text">{reveal.fresh ? 'Then, with the path to your repo:' : 'Connect your repo again with it:'}</p>
      <CodeBlock lines={connectCommands(reveal.key)} label="the commands" />

      <p className="mt-5 max-w-[620px] text-[14px] leading-relaxed text-muted">{WHAT_IS_SENT}</p>
    </motion.section>
  )
}

function flying(n: number) {
  if (!n) return 'No agents flying'
  return n === 1 ? '1 agent flying' : `${n} agents flying`
}

type Confirming = 'key' | 'delete' | null

function WorkspaceRow({ workspace, onKey, onDeleted }: { workspace: Workspace; onKey: (key: string) => void; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState<Confirming>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const date = shortDate(workspace.created_at)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      if (confirming === 'key') onKey(await rotateKey(workspace.id))
      else {
        await deleteWorkspace(workspace.id)
        onDeleted()
      }
      setConfirming(null)
      void refreshMe()
    } catch (e) {
      setError(failure(e, confirming === 'key' ? 'The key was not changed.' : 'The workspace was not deleted.'))
    } finally {
      setBusy(false)
    }
  }

  const ask = (what: Confirming) => {
    setError(null)
    setConfirming(what)
  }

  return (
    <li className="px-5 py-4 sm:px-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <p className="truncate text-[15.5px] font-semibold text-text">{workspace.name}</p>
          <p className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[13.5px] text-muted">
            <span className="font-mono text-[12.5px] text-text" title="The start of the live key">
              {workspace.key_prefix}…
            </span>
            <span className={workspace.agents_flying ? 'text-ok' : ''}>{flying(workspace.agents_flying)}</span>
            {date && <span>Created {date}</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <a href={workspacePath(workspace.id)} className={`${buttonClass('secondary')} mr-1`}>
            Open Tower <ArrowRight size={14} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
          </a>
          <Button tone="quiet" onClick={() => ask('key')} disabled={busy}>
            New key
          </Button>
          <Button tone="quiet" onClick={() => ask('delete')} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>

      <AnimatePresence initial={false}>
        {confirming && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.25, ease }} className="overflow-hidden">
            <div className="mt-4 rounded-[10px] bg-surface-2 px-4 py-3.5" role="alertdialog" aria-label={confirming === 'key' ? 'Make a new key' : 'Delete the workspace'}>
              <p className="text-[14px] leading-relaxed text-text">
                {confirming === 'key'
                  ? 'Make a new key? The old key stops working at once, so every repo connected with it needs the new one.'
                  : `Delete ${workspace.name}? Its graph and its key go with it. This cannot be undone.`}
              </p>
              {error && (
                <p className="mt-2 text-[13.5px] text-bad" role="alert">
                  {error}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button tone={confirming === 'key' ? 'primary' : 'danger'} onClick={run} disabled={busy}>
                  {confirming === 'key' ? (busy ? 'Making a key' : 'Make a new key') : busy ? 'Deleting' : 'Delete workspace'}
                </Button>
                <Button onClick={() => setConfirming(null)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

function NewWorkspace({ count, onCreated }: { count: number; onCreated: (w: Workspace, key: string) => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = useId()
  const full = count >= WORKSPACE_LIMIT

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const clean = name.trim()
    if (!clean) return setError('Give it a name.')
    if (clean.length > NAME_MAX) return setError(`Use at most ${NAME_MAX} characters.`)
    setBusy(true)
    setError(null)
    try {
      const { workspace, key } = await createWorkspace(clean)
      setName('')
      onCreated(workspace, key)
      void refreshMe()
    } catch (err) {
      setError(failure(err, 'The workspace was not created.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mt-6 rounded-[14px] border border-line bg-surface p-5 sm:p-6">
      <label htmlFor={id} className="text-[15.5px] font-semibold text-text">
        New workspace
      </label>
      <p className="mt-1 text-[14px] text-muted">One per repo. Name it after the repo.</p>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row">
        <input
          id={id}
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            if (error) setError(null)
          }}
          maxLength={NAME_MAX}
          disabled={full || busy}
          placeholder="my-repo"
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          aria-invalid={!!error}
          aria-describedby={`${id}-note`}
          className={`h-10 w-full min-w-0 rounded-[8px] bg-bg px-3 text-[14.5px] text-text placeholder:text-faint focus:outline-none focus-visible:outline-none disabled:opacity-50 sm:flex-1 ${
            error ? 'shadow-[inset_0_0_0_1px_var(--bad)]' : 'shadow-[inset_0_0_0_1px_var(--line-strong)] focus:shadow-[inset_0_0_0_1px_var(--muted)]'
          }`}
        />
        <Button type="submit" tone="primary" disabled={full || busy} size="md">
          {busy ? 'Creating' : 'Create workspace'}
        </Button>
      </div>
      <p id={`${id}-note`} className={`mt-2 text-[13px] leading-snug ${error ? 'text-bad' : 'text-faint'}`} aria-live="polite">
        {error ?? (full ? `You have ${WORKSPACE_LIMIT} workspaces, the most there can be. Delete one to make another.` : `${count} of ${WORKSPACE_LIMIT} workspaces used. Names are 1 to ${NAME_MAX} characters.`)}
      </p>
    </form>
  )
}

const steps = [
  { title: 'Make a workspace', text: 'Name it after the repo. You get a key, shown once.' },
  { title: 'Connect the repo', text: 'Run the connect command with the key, then install the hooks.' },
  { title: 'Open Tower', text: 'Start Claude Code sessions in the repo and watch them live.' },
]

function NoWorkspaces() {
  return (
    <section className="mt-10 rounded-[14px] border border-line bg-surface p-5 sm:p-6" aria-label="No workspaces yet">
      <h2 className="text-[15.5px] font-semibold text-text">No workspaces yet</h2>
      <ol className="mt-5 grid gap-5 sm:grid-cols-3 sm:gap-6">
        {steps.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[22px_minmax(0,1fr)] sm:block">
            <span className="text-[14px] font-semibold text-faint tabular-nums">{i + 1}</span>
            <div className="sm:mt-2">
              <p className="text-[14.5px] font-semibold text-text">{s.title}</p>
              <p className="mt-1 text-[14px] leading-relaxed text-muted">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** Two quiet airspaces, the shape Tower fills once agents fly. */
function EmptyScope() {
  return (
    <svg viewBox="0 0 150 104" className="h-14 w-auto text-line-strong" aria-hidden="true">
      <circle cx="52" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="98" cy="52" r="44" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}

function Prompt({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="max-w-[480px] py-10 sm:py-16">
      <EmptyScope />
      <h1 className="mt-6 text-[26px] leading-tight font-semibold tracking-[-0.025em] text-text text-balance sm:text-[30px]">{title}</h1>
      {children}
    </div>
  )
}

function Loading() {
  return (
    <div className="pt-2" aria-busy="true" aria-label="Loading your workspaces">
      <div className="h-9 w-48 rounded-[8px] bg-surface-2" />
      <div className="mt-4 h-4 w-80 max-w-full rounded bg-surface-2" />
      <div className="mt-10 h-[148px] rounded-[14px] border border-line bg-surface" />
    </div>
  )
}

function Workspaces({ workspaces }: { workspaces: Workspace[] }) {
  const [reveal, setReveal] = useState<Reveal | null>(null)

  return (
    <>
      <h1 className="text-[34px] leading-tight font-semibold tracking-[-0.03em] text-text sm:text-[40px]">Workspaces</h1>
      <p className="mt-3 max-w-[580px] text-[16px] leading-relaxed text-muted text-pretty">A workspace holds the code graph of one repo. The repo's hooks report to it with a key, and Tower shows your sessions live.</p>

      <AnimatePresence>{reveal && <KeyReveal key={reveal.key} reveal={reveal} onDone={() => setReveal(null)} />}</AnimatePresence>

      {workspaces.length ? (
        <section className="mt-10" aria-label="Your workspaces">
          <ul className="divide-y divide-line overflow-hidden rounded-[14px] border border-line bg-surface">
            {workspaces.map((w) => (
              <WorkspaceRow
                key={w.id}
                workspace={w}
                onKey={(key) => setReveal({ workspace: w.name, key, fresh: false })}
                onDeleted={() => setReveal((r) => (r?.workspace === w.name ? null : r))}
              />
            ))}
          </ul>
        </section>
      ) : (
        <NoWorkspaces />
      )}

      <NewWorkspace count={workspaces.length} onCreated={(w, key) => setReveal({ workspace: w.name, key, fresh: true })} />
    </>
  )
}

/** /app: your workspaces, or a sign-in prompt. */
export default function AppPage() {
  const me = useMe()

  useEffect(() => {
    document.title = 'Workspaces | Airspace'
  }, [])

  let body: ReactNode
  if (me.status === 'loading') body = <Loading />
  else if (me.status === 'error')
    body = (
      <Prompt title="Your workspaces did not load.">
        <p className="mt-3 text-[16px] leading-relaxed text-muted">{me.message}</p>
        <Button onClick={() => void refreshMe()} size="md" className="mt-6">
          <ArrowClockwise size={15} weight="bold" /> Try again
        </Button>
      </Prompt>
    )
  else if (me.me.user) body = <Workspaces workspaces={me.me.workspaces} />
  else if (me.me.signin)
    body = (
      <Prompt title="Sign in to use workspaces.">
        <p className="mt-3 text-[16px] leading-relaxed text-muted text-pretty">A workspace connects one of your repos to Tower here, so you can watch your own Claude Code sessions live.</p>
        <SignInButton next="/app" className="mt-7" />
        <p className="mt-4 text-[13.5px] text-faint">Airspace only reads your GitHub profile.</p>
      </Prompt>
    )
  else
    body = (
      <Prompt title="Workspaces are not available on this server.">
        <p className="mt-3 text-[16px] leading-relaxed text-muted text-pretty">Sign-in is not set up here. Run Airspace on your own machine to watch your sessions, or open the demo Tower.</p>
        <ButtonLink href="/tower" variant="secondary" className="mt-7">
          Open the demo Tower
        </ButtonLink>
      </Prompt>
    )

  return (
    <div className="flex min-h-dvh flex-col">
      <Nav />
      <main className="flex-1">
        <Container className="pt-12 pb-24 sm:pt-16 sm:pb-32">
          <div className="max-w-[820px]">{body}</div>
        </Container>
      </main>
    </div>
  )
}
