import type { ReactNode } from 'react'

/** Tower's buttons: orange for the one primary action, a hairline for the rest. */
export function Action({ onClick, disabled, primary, type = 'button', children }: { onClick?: () => void; disabled?: boolean; primary?: boolean; type?: 'button' | 'submit'; children: ReactNode }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-9 items-center gap-2 rounded-[8px] px-3 text-[13.5px] font-semibold whitespace-nowrap transition-[transform,opacity,background-color,color] active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40 ${
        primary ? 'bg-accent text-accent-ink hover:brightness-[1.07]' : 'text-text shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2'
      }`}
    >
      {children}
    </button>
  )
}
