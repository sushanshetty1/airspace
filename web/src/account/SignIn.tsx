import { GithubLogo } from '@phosphor-icons/react'
import { ButtonLink } from '../ui'
import { signInHref } from './api'

/** Off to GitHub, then back to `next`. */
export function SignInButton({ next, className = '' }: { next: string; className?: string }) {
  return (
    <ButtonLink href={signInHref(next)} className={className}>
      <GithubLogo size={18} weight="bold" />
      Sign in with GitHub
    </ButtonLink>
  )
}
