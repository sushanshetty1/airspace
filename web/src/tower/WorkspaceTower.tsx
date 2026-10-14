import { ArrowClockwise } from '@phosphor-icons/react'
import { useEffect, type ReactNode } from 'react'
import { refreshMe, useMe } from '../account/api'
import { SignInButton } from '../account/SignIn'
import { ButtonLink } from '../ui'
import { Notice, Skeleton, TopBar, WorkspaceTowerView } from './Tower'

function Shell({ children, name }: { children: ReactNode; name?: string }) {
  return (
    <div className="flex min-h-dvh flex-col bg-bg text-text lg:h-dvh">
      <TopBar conn={null} workspace={{ id: '', name: name ?? '' }} />
      {children}
    </div>
  )
}

/** /w/:id: the signed-in owner's workspace in Tower. Signed out, a sign-in prompt; someone else's or a deleted one, not found. */
export default function WorkspaceTower({ id, collisionId }: { id: string; collisionId: string | null }) {
  const me = useMe()

  useEffect(() => {
    document.title = 'Tower | Airspace'
  }, [])

  if (me.status === 'loading')
    return (
      <Shell>
        <Skeleton />
      </Shell>
    )

  if (me.status === 'error')
    return (
      <Shell>
        <Notice title="Tower could not reach the Airspace server.">
          <p className="mt-2 text-[15px] leading-relaxed text-muted">{me.message}</p>
          <button
            type="button"
            onClick={() => void refreshMe()}
            className="mt-5 inline-flex h-9 items-center gap-2 rounded-[8px] px-3 text-[13.5px] font-semibold text-text shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors hover:bg-surface-2"
          >
            <ArrowClockwise size={15} weight="bold" /> Try again
          </button>
        </Notice>
      </Shell>
    )

  const { user, workspaces, signin } = me.me
  if (!user)
    return (
      <Shell>
        {signin ? (
          <Notice title="Sign in to open this workspace.">
            <p className="mt-2 text-[15px] leading-relaxed text-muted">Workspaces are private to the GitHub account that made them.</p>
            <SignInButton next={window.location.pathname} className="mt-6" />
          </Notice>
        ) : (
          <Notice title="This server has no workspaces.">
            <p className="mt-2 text-[15px] leading-relaxed text-muted">Sign-in is not set up here. The demo Tower shows a recorded run.</p>
            <ButtonLink href="/tower" variant="secondary" className="mt-6">
              Open the demo Tower
            </ButtonLink>
          </Notice>
        )}
      </Shell>
    )

  const workspace = workspaces.find((w) => w.id === id)
  if (!workspace)
    return (
      <Shell>
        <Notice title="There is no workspace here.">
          <p className="mt-2 text-[15px] leading-relaxed text-muted">It was deleted, or it belongs to another account.</p>
          <ButtonLink href="/app" variant="secondary" className="mt-6">
            Your workspaces
          </ButtonLink>
        </Notice>
      </Shell>
    )

  return <WorkspaceTowerView workspace={{ id: workspace.id, name: workspace.name }} collisionId={collisionId} />
}
