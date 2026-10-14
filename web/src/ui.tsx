import { useId, type ComponentProps, type ReactNode } from 'react'

export const REPO_URL = 'https://github.com/sushanshetty1/airspace'
export const PAPER_URL = 'https://arxiv.org/abs/2609.25396'

/** A link to a home page section, from the home page or from another page such as /playground. */
export const sectionHref = (id: string) => (window.location.pathname === '/' ? `#${id}` : `/#${id}`)

/** Two overlapping airspaces; the orange lens is where they meet. */
export function LogoMark({ className = 'h-6 w-auto' }: { className?: string }) {
  const clip = `logo${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  return (
    <svg viewBox="0 0 150 104" className={className} aria-hidden="true">
      <defs>
        <clipPath id={clip}>
          <circle cx="52" cy="52" r="46" />
        </clipPath>
      </defs>
      <circle cx="98" cy="52" r="46" fill="var(--accent)" clipPath={`url(#${clip})`} />
      <circle cx="52" cy="52" r="42" fill="none" stroke="currentColor" strokeWidth="9" />
      <circle cx="98" cy="52" r="42" fill="none" stroke="currentColor" strokeWidth="9" />
    </svg>
  )
}

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 text-text ${className}`}>
      <LogoMark className="h-[19px] w-auto" />
      <span className="text-[17px] font-semibold tracking-[-0.02em]">Airspace</span>
    </span>
  )
}

export function Container({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`mx-auto w-full max-w-[1200px] px-5 sm:px-8 ${className}`}>{children}</div>
}

type ButtonProps = ComponentProps<'a'> & { variant?: 'primary' | 'secondary' }

export function ButtonLink({ variant = 'primary', className = '', children, ...rest }: ButtonProps) {
  const base =
    'group inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[8px] px-[18px] text-[15px] font-semibold transition-[transform,background-color,color,box-shadow] duration-200 ease-out active:scale-[0.98]'
  const styles =
    variant === 'primary'
      ? 'bg-accent text-accent-ink hover:brightness-[1.07]'
      : 'text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2'
  return (
    <a className={`${base} ${styles} ${className}`} {...rest}>
      {children}
    </a>
  )
}

export type SignKind = 'HOLD' | 'CLEARED' | 'BRIEFED' | 'FILED' | 'CONTRACT' | 'LOCATION'

const signClass: Record<SignKind, string> = {
  HOLD: 'sign-hold',
  CLEARED: 'sign-cleared',
  BRIEFED: 'sign-briefed',
  FILED: 'sign-filed',
  CONTRACT: 'sign-contract',
  LOCATION: 'sign-location',
}

export const signLabel: Record<Exclude<SignKind, 'LOCATION'>, string> = {
  HOLD: 'Hold',
  CLEARED: 'Cleared',
  BRIEFED: 'Briefed',
  FILED: 'Plan filed',
  CONTRACT: 'Changing',
}

/** Status badge. Colour is never the only signal: the word is always there. */
export function Sign({ kind, children, className = '' }: { kind: SignKind; children: ReactNode; className?: string }) {
  return <span className={`sign ${signClass[kind]} ${className}`}>{children}</span>
}

/** A product window: one hairline, real app proportions. */
export function Frame({ title, right, className = '', children }: { title: ReactNode; right?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className={`overflow-hidden rounded-[12px] border border-line bg-surface ${className}`}>
      <div className="flex h-11 items-center justify-between gap-4 border-b border-line px-4">
        <div className="flex min-w-0 items-center gap-2.5 text-[13.5px]">{title}</div>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </div>
      {children}
    </div>
  )
}

export function SectionHeading({ title, lede, className = '' }: { title: ReactNode; lede?: ReactNode; className?: string }) {
  return (
    <div className={`max-w-[720px] ${className}`}>
      <h2 className="display text-[36px] text-balance sm:text-[48px]">{title}</h2>
      {lede && <p className="mt-4 max-w-[580px] text-[18px] leading-relaxed text-muted text-pretty">{lede}</p>}
    </div>
  )
}
