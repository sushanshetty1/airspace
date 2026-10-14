import { useId, type ComponentProps, type ReactNode } from 'react'

export const REPO_URL = 'https://github.com/sushanshetty1/airspace'
export const PAPER_URL = 'https://arxiv.org/abs/2609.25396'

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

export function Container({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`mx-auto w-full max-w-[1240px] px-5 sm:px-8 ${className}`}>{children}</div>
}

type ButtonProps = ComponentProps<'a'> & { variant?: 'primary' | 'secondary' }

export function ButtonLink({ variant = 'primary', className = '', children, ...rest }: ButtonProps) {
  const base =
    'group inline-flex h-12 items-center justify-center gap-2.5 whitespace-nowrap rounded-[3px] px-5 text-[15px] font-semibold transition-[transform,background-color,color,box-shadow] duration-200 ease-out active:translate-y-px'
  const styles =
    variant === 'primary'
      ? 'bg-accent text-accent-ink hover:bg-text hover:text-bg'
      : 'text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:shadow-[inset_0_0_0_1px_var(--text)]'
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

/** Airfield-style status sign. Colour is never the only signal: the word is always there. */
export function Sign({ kind, children, className = '' }: { kind: SignKind; children: ReactNode; className?: string }) {
  return <span className={`sign ${signClass[kind]} ${className}`}>{children}</span>
}

/** Mono caption for figures, in the style of a technical drawing. */
export function Fig({ n, children, className = '' }: { n: string; children: ReactNode; className?: string }) {
  return (
    <p className={`flex items-center gap-3 font-label text-[11px] tracking-[0.12em] text-faint uppercase ${className}`}>
      <span className="shrink-0 whitespace-nowrap text-muted">FIG. {n}</span>
      <span className="h-px w-6 shrink-0 bg-line-strong" aria-hidden="true" />
      <span className="max-sm:hidden">{children}</span>
    </p>
  )
}

/** Corner brackets that frame a figure, like registration marks on a drawing. */
export function Brackets({ className = '', children }: { className?: string; children: ReactNode }) {
  const corner = 'pointer-events-none absolute size-3.5 border-text/40'
  return (
    <div className={`relative ${className}`}>
      <span className={`${corner} top-0 left-0 border-t border-l`} aria-hidden="true" />
      <span className={`${corner} top-0 right-0 border-t border-r`} aria-hidden="true" />
      <span className={`${corner} bottom-0 left-0 border-b border-l`} aria-hidden="true" />
      <span className={`${corner} right-0 bottom-0 border-r border-b`} aria-hidden="true" />
      {children}
    </div>
  )
}

/** A product window: square corners, one hairline, no glow. */
export function Frame({ title, right, className = '', children }: { title: ReactNode; right?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <div className={`overflow-hidden rounded-[4px] border border-line bg-surface ${className}`}>
      <div className="flex h-11 items-center justify-between gap-4 border-b border-line px-4">
        <div className="flex min-w-0 items-center gap-2.5 text-[13px]">{title}</div>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </div>
      {children}
    </div>
  )
}

export function SectionHeading({ title, lede, className = '' }: { title: ReactNode; lede?: ReactNode; className?: string }) {
  return (
    <div className={`max-w-[760px] ${className}`}>
      <h2 className="display text-[34px] text-balance sm:text-[46px]">{title}</h2>
      {lede && <p className="mt-5 max-w-[600px] text-[17px] leading-relaxed text-muted text-pretty sm:text-[18px]">{lede}</p>}
    </div>
  )
}
