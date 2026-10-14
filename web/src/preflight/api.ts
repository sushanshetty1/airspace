// Pre-flight: which tasks can run in parallel and which must coordinate, before any agent starts.
// Shapes follow docs/superpowers/plans/2026-10-14-preflight.md.

export type DemoRepo = { id: string; name: string; symbols: number }

export type SymbolHit = { qualname: string; kind: string; signature: string | null }

export type TaskInput = { name: string; symbols: string[] }

/** What earlier sessions left on a task's symbols and their dependents. Older servers send none. */
export type TaskHistory = { collisions?: number; notes?: number; changes?: number; last_at?: number | null }

export type PairKind = 'same_symbol' | 'calls' | 'shared_dependents'

export type PreflightAnswer = {
  tasks: { name: string; symbols: string[]; cone: number; cone_sample: string[]; history?: TaskHistory | null }[]
  pairs: { a: string; b: string; kind: PairKind; symbols: string[]; path: string[]; shared: number }[]
  groups: { tasks: string[]; coordinate: boolean }[]
  hot: { qualname: string; betweenness: number }[]
  summary: string
}

/** Where the check runs: a bundled demo repo, or one of the signed-in user's workspaces. */
export type Target = { kind: 'demo'; id: string } | { kind: 'workspace'; id: string }

export class PreflightError extends Error {
  status: number
  suggestions: string[]
  constructor(status: number, message: string, suggestions: string[] = []) {
    super(message)
    this.status = status
    this.suggestions = suggestions
  }
}

/** The repos the demo server has indexed. Until it answers, the two it normally has. */
export const DEFAULT_REPOS: DemoRepo[] = [
  { id: 'flask', name: 'Flask', symbols: 0 },
  { id: 'blog', name: 'Sample blog', symbols: 0 },
]

const enc = encodeURIComponent

async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {}
  // The hosted server refuses cookie-authenticated writes without it.
  if (method === 'POST') headers['X-Airspace'] = '1'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, { method, headers, credentials: 'same-origin', signal, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new PreflightError(0, 'The Airspace server did not answer. Try again in a moment.')
  }
  const data = (await res.json().catch(() => null)) as (T & { error?: unknown; detail?: unknown; suggestions?: unknown }) | null
  if (!res.ok || data === null) {
    const suggestions = Array.isArray(data?.suggestions) ? [...new Set(data.suggestions.filter((s): s is string => typeof s === 'string'))] : []
    let message = typeof data?.error === 'string' ? data.error : typeof data?.detail === 'string' ? data.detail : ''
    if (!message) {
      if (res.status === 429) message = 'Too many checks from this address. Try again in a minute.'
      else if (res.status === 401) message = 'Sign in again to use this workspace.'
      else if (res.status === 404) message = 'This server has no pre-flight yet.'
      else if (res.status === 422) message = 'The server could not read these tasks.'
      else message = `The server answered ${res.status}.`
    }
    throw new PreflightError(res.status, message, suggestions)
  }
  return data
}

export async function fetchRepos(): Promise<DemoRepo[]> {
  const data = await call<{ repos?: DemoRepo[] }>('GET', '/api/preflight/repos')
  return Array.isArray(data.repos) ? data.repos : []
}

export async function searchSymbols(target: Target, q: string, signal?: AbortSignal): Promise<SymbolHit[]> {
  const path = target.kind === 'demo' ? `/api/preflight/symbols?repo=${enc(target.id)}&q=${enc(q)}` : `/api/w/${enc(target.id)}/preflight/symbols?q=${enc(q)}`
  const data = await call<{ symbols?: SymbolHit[] }>('GET', path, undefined, signal)
  return Array.isArray(data.symbols) ? data.symbols : []
}

export async function runPreflight(target: Target, tasks: TaskInput[]): Promise<PreflightAnswer> {
  if (target.kind === 'demo') return call<PreflightAnswer>('POST', '/api/preflight', { repo: target.id, tasks })
  return call<PreflightAnswer>('POST', `/api/w/${enc(target.id)}/preflight`, { tasks })
}

/** The symbol a server message is about: "No symbol named X." or "X matches several symbols." */
export function symbolOf(message: string): string | null {
  const m = /^No symbol named (.+)\.$/.exec(message) ?? /^(.+) matches several symbols\.$/.exec(message)
  return m ? m[1] : null
}
