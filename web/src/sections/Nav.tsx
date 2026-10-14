import { GithubLogo, List, Moon, Sun, X } from '@phosphor-icons/react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { ButtonLink, Container, LogoMark, REPO_URL } from '../ui'

type Theme = 'light' | 'dark'

function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme
  if (set === 'light' || set === 'dark') return set
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('dark')
  useEffect(() => setTheme(currentTheme()), [])

  const flip = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('airspace-theme', next)
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
    setTheme(next)
  }

  return (
    <button
      type="button"
      onClick={flip}
      aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      className="grid size-9 place-items-center text-muted transition-colors hover:text-text"
    >
      {theme === 'dark' ? <Sun size={18} weight="bold" /> : <Moon size={18} weight="bold" />}
    </button>
  )
}

const links = [
  { id: 'how', label: 'How it works' },
  { id: 'tower', label: 'Tower' },
  { id: 'graph', label: 'Why a graph' },
  { id: 'proof', label: 'Results' },
]

/** Which section is under the nav right now, so the matching link can light up. */
function useActiveSection() {
  const [active, setActive] = useState<string | null>(null)
  useEffect(() => {
    // The hero and the problem section have no nav link; reaching them clears the highlight.
    const ids = ['top', 'problem', ...links.map((l) => l.id), 'start']
    const els = ids.map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[]
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(links.some((l) => l.id === e.target.id) ? e.target.id : null)
      },
      { rootMargin: '-45% 0px -50% 0px' },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])
  return active
}

export function Nav() {
  const active = useActiveSection()
  const [open, setOpen] = useState(false)

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/[0.97] backdrop-blur-md">
      <Container className="flex h-16 items-center justify-between gap-6">
        <a href="#top" className="flex items-center gap-3 text-text" aria-label="Airspace home">
          <LogoMark className="h-[20px] w-auto" />
          <span className="text-[16px] font-bold tracking-[0.02em] uppercase" style={{ fontStretch: '125%' }}>
            Airspace
          </span>
        </a>

        <nav className="hidden h-full items-stretch md:flex" aria-label="Sections">
          {links.map((l) => {
            const on = active === l.id
            return (
              <a
                key={l.id}
                href={`#${l.id}`}
                aria-current={on ? 'true' : undefined}
                className={`relative flex items-center px-4 text-[14px] font-medium transition-colors ${on ? 'text-text' : 'text-muted hover:text-text'}`}
              >
                {l.label}
                {on && <motion.span layoutId="nav-active" className="absolute inset-x-4 -bottom-px h-[2px] bg-accent" transition={{ type: 'spring', stiffness: 420, damping: 36 }} />}
              </a>
            )
          })}
        </nav>

        <div className="flex items-center gap-1">
          <ThemeToggle />
          <a href={REPO_URL} className="grid size-9 place-items-center text-muted transition-colors hover:text-text" aria-label="View on GitHub">
            <GithubLogo size={19} weight="bold" />
          </a>
          <ButtonLink href="#tower" className="ml-2 h-9 px-4 text-[14px] max-sm:hidden">
            See it run
          </ButtonLink>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? 'Close menu' : 'Open menu'}
            className="grid size-9 place-items-center text-text md:hidden"
          >
            {open ? <X size={20} weight="bold" /> : <List size={20} weight="bold" />}
          </button>
        </div>
      </Container>

      <AnimatePresence>
        {open && (
          <motion.nav
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden border-t border-line md:hidden"
            aria-label="Sections"
          >
            <Container className="flex flex-col py-3">
              {links.map((l) => (
                <a key={l.id} href={`#${l.id}`} onClick={() => setOpen(false)} className="border-b border-line py-3.5 text-[16px] font-medium text-text last:border-b-0">
                  {l.label}
                </a>
              ))}
            </Container>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  )
}
