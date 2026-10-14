// Accounts and workspaces on the hosted server: who is signed in, their workspaces and keys.
// Shapes follow docs/superpowers/plans/2026-10-14-accounts-and-workspaces.md.

import { useSyncExternalStore } from 'react'
import { ApiError, request } from '../tower/api'

export type User = { login: string; name: string | null; avatar_url: string | null }

export type Workspace = {
  id: string
  name: string
  /** Unix seconds, or an ISO date, as the server sends it. */
  created_at: number | string
  /** The first 12 characters of the live key, for display. */
  key_prefix: string
  agents_flying: number
}

export type Me = {
  user: User | null
  workspaces: Workspace[]
  /** Whether sign-in is configured on this server. */
  signin: boolean
}

export const WORKSPACE_LIMIT = 5
export const NAME_MAX = 60

/** A server without accounts: nothing to sign in to, nothing new in the nav. */
const NO_ACCOUNTS: Me = { user: null, workspaces: [], signin: false }

export type MeState = { status: 'loading' } | { status: 'ready'; me: Me } | { status: 'error'; message: string }

// One shared copy of /api/me for the nav and the pages.
let current: MeState = { status: 'loading' }
let started = false
const listeners = new Set<() => void>()

function set(next: MeState) {
  current = next
  listeners.forEach((l) => l())
}

/** Fetches /api/me again and tells every view. */
export async function refreshMe() {
  started = true
  try {
    const me = await request<Me>('GET', '/api/me')
    set({ status: 'ready', me: { user: me?.user ?? null, workspaces: Array.isArray(me?.workspaces) ? me.workspaces : [], signin: !!me?.signin } })
  } catch (e) {
    // A server from before accounts has no /api/me.
    if (e instanceof ApiError && e.status === 404) set({ status: 'ready', me: NO_ACCOUNTS })
    else set({ status: 'error', message: e instanceof Error ? e.message : 'The server did not answer.' })
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (!started) void refreshMe()
  return () => listeners.delete(listener)
}

export function useMe(): MeState {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  )
}

/** Where the sign-in button goes: GitHub, then back to `next` on this site. */
export const signInHref = (next: string) => `/auth/github/login?next=${encodeURIComponent(next)}`

export async function createWorkspace(name: string) {
  return request<{ workspace: Workspace; key: string }>('POST', '/api/workspaces', { name })
}

/** A new key for the workspace. The old one stops working at once. */
export async function rotateKey(id: string) {
  return (await request<{ key: string }>('POST', `/api/workspaces/${encodeURIComponent(id)}/key`)).key
}

export async function deleteWorkspace(id: string) {
  await request<{ ok: boolean }>('DELETE', `/api/workspaces/${encodeURIComponent(id)}`)
}

export async function signOut() {
  await request<{ ok: boolean }>('POST', '/auth/logout')
}

/** The two commands that point a repo's hooks at a workspace. */
export function connectCommands(key: string, server = window.location.origin) {
  return [`uv run airspace connect --root ~/your-repo --server ${server} --key ${key}`, 'uv run airspace install-hooks --root ~/your-repo']
}

export const WHAT_IS_SENT = 'Your hooks send symbol names, signatures, call shapes and the one-line text of calls. Whole files stay on your machine.'

/** 14 Oct 2026. */
export function shortDate(value: number | string) {
  const d = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}
