import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useId, useRef, useState } from 'react'
import { refreshMe, signInHref, signOut, useMe, type User } from './api'

export function Avatar({ user, className = 'size-7' }: { user: User; className?: string }) {
  const [broken, setBroken] = useState(false)
  if (user.avatar_url && !broken)
    return <img src={user.avatar_url} alt="" onError={() => setBroken(true)} className={`${className} shrink-0 rounded-full bg-surface-2 object-cover`} />
  return (
    <span className={`${className} grid shrink-0 place-items-center rounded-full bg-surface-2 text-[12px] font-semibold text-text`} aria-hidden="true">
      {user.login.slice(0, 1).toUpperCase()}
    </span>
  )
}

function UserMenu({ user }: { user: User }) {
  const [open, setOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const onApp = window.location.pathname === '/app'

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const leave = async () => {
    setLeaving(true)
    try {
      await signOut()
    } catch {
      // The cookie may already be gone; /api/me says where things stand.
    }
    await refreshMe()
    setLeaving(false)
    setOpen(false)
  }

  return (
    <div ref={root} className="relative ml-1.5">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={`Account, signed in as ${user.login}`}
        className="grid size-9 place-items-center rounded-full"
      >
        <Avatar user={user} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            id={menuId}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            className="absolute top-full right-0 z-40 mt-2 w-56 overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_12px_32px_rgb(0_0_0/0.18)]"
          >
            <div className="border-b border-line px-3.5 py-3">
              <p className="truncate text-[14px] font-semibold text-text">{user.name || user.login}</p>
              {user.name && <p className="truncate text-[13px] text-muted">{user.login}</p>}
            </div>
            <div className="p-1.5">
              <a
                href="/app"
                aria-current={onApp ? 'page' : undefined}
                className="flex h-9 items-center rounded-[6px] px-2.5 text-[14px] font-medium text-text transition-colors hover:bg-surface-2"
              >
                Workspaces
              </a>
              <button
                type="button"
                onClick={leave}
                disabled={leaving}
                className="flex h-9 w-full items-center rounded-[6px] px-2.5 text-left text-[14px] font-medium text-text transition-colors hover:bg-surface-2 disabled:opacity-60"
              >
                {leaving ? 'Signing out' : 'Sign out'}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** The avatar and its menu, when signed in. */
export function AccountButton() {
  const me = useMe()
  if (me.status !== 'ready' || !me.me.user) return null
  return <UserMenu user={me.me.user} />
}

/** A quiet sign-in link, when signed out on a server with sign-in. Nothing on a server without accounts. */
export function SignInLink() {
  const me = useMe()
  if (me.status !== 'ready' || me.me.user || !me.me.signin) return null
  return (
    <a href={signInHref('/app')} className="ml-2 flex h-9 items-center px-1.5 text-[14.5px] font-medium whitespace-nowrap text-muted transition-colors hover:text-text max-lg:hidden">
      Sign in
    </a>
  )
}

/** The phone menu's sign-in row, when signed out. */
export function AccountMenuLink({ onNavigate }: { onNavigate: () => void }) {
  const me = useMe()
  if (me.status !== 'ready' || me.me.user || !me.me.signin) return null
  return (
    <a href={signInHref('/app')} onClick={onNavigate} className="border-t border-line py-3.5 text-[16px] font-medium text-text">
      Sign in
    </a>
  )
}
