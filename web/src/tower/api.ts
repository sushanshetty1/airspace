// Typed client for `airspace serve`. Shapes follow the Phase 2 contract
// (docs/superpowers/plans/2026-10-14-phase-2-tower-mcp-memory.md).

export type Resolution = 'held' | 'released' | 'resolved'

export type EventKind = 'plan' | 'cleared' | 'hold' | 'briefed' | 'contract' | 'paused' | 'resumed' | 'released' | 'message' | 'resolved'

export type AgentState = {
  id: string
  paused: boolean
  status: string
  tasks: string[]
  claims: string[]
  /** Has an open (resolution = held) collision as the held agent. */
  held: boolean
}

export type CollisionSummary = {
  id: string
  at: number
  kind: string
  symbol: string
  held_agent: string
  owner_agent: string
  resolution: Resolution
}

export type StateData = {
  now: number
  agents: AgentState[]
  /** Newest first, at most 20. */
  collisions: CollisionSummary[]
  /** Not in the contract yet; shown in the top bar when the server sends it. */
  repo?: string
}

export type RadarAgent = {
  id: string
  center: string | null
  claims: string[]
  cone: { qualname: string; hop: number }[]
}

export type RadarSymbol = { label: string; kind: string; is_test: boolean }

export type RadarCollision = {
  id: string
  symbol: string
  caller: string | null
  held_agent: string
  owner_agent: string
  resolution: Resolution
}

export type RadarData = {
  /** At most the 4 most recently active agents. */
  agents: RadarAgent[]
  symbols: Record<string, RadarSymbol>
  /** [from, to] for CALLS, COVERS and INHERITS among the listed symbols. */
  edges: [string, string][]
  collision: RadarCollision | null
}

export type CollisionDetail = {
  id: string
  at: number
  kind: string
  symbol: string
  caller: string | null
  path: string[]
  held_agent: string
  held_task: string
  owner_agent: string
  owner_task: string
  old_sig?: string | null
  new_sig?: string | null
  resolution: Resolution
}

export type AirEvent = {
  id: string
  at: number
  kind: EventKind
  agent: string
  task?: string | null
  text: string
  code: string
}

export const MESSAGE_MAX = 500

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** What Tower needs from a server. The HTTP client and the mock both implement it. */
export interface TowerApi {
  state(): Promise<StateData>
  radar(): Promise<RadarData>
  events(since: number): Promise<AirEvent[]>
  /** null when the server has no such collision. */
  collision(id: string): Promise<CollisionDetail | null>
  pause(agent: string): Promise<void>
  resume(agent: string): Promise<void>
  message(agent: string, text: string): Promise<string>
  release(id: string): Promise<boolean>
  /**
   * Opens the live event stream. Calls onEvent for each event, onOpen when connected
   * and onError when the stream drops. Returns a function that closes it.
   */
  stream(since: number, handlers: { onEvent: (e: AirEvent) => void; onOpen: () => void; onError: () => void }): () => void
}

/**
 * A JSON request. Every POST and DELETE carries `X-Airspace: 1`: the hosted server
 * refuses cookie-authenticated writes without it, which blocks cross-site form posts.
 */
export async function request<T>(method: 'GET' | 'POST' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-Airspace'] = '1'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'The Airspace server did not answer.')
  }
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    // An empty or non JSON body; the status says enough.
  }
  if (!res.ok) {
    const body = (data ?? {}) as { error?: unknown; detail?: unknown }
    const detail = typeof body.error === 'string' ? body.error : typeof body.detail === 'string' ? body.detail : ''
    throw new ApiError(res.status, detail || `The server answered ${res.status}.`)
  }
  return data as T
}

const enc = encodeURIComponent

/**
 * The HTTP client for a Tower API rooted at `base`: `/api` for the server's own graph,
 * `/api/w/<id>` for a hosted workspace.
 */
export function createHttpApi(base: string): TowerApi {
  return {
    state: () => request<StateData>('GET', `${base}/state`),
    radar: () => request<RadarData>('GET', `${base}/radar`),
    events: async (since) => (await request<{ events: AirEvent[] }>('GET', `${base}/events?since=${since}`)).events,
    collision: async (id) => {
      try {
        return await request<CollisionDetail>('GET', `${base}/collisions/${enc(id)}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
    pause: async (agent) => {
      await request('POST', `${base}/agents/${enc(agent)}/pause`)
    },
    resume: async (agent) => {
      await request('POST', `${base}/agents/${enc(agent)}/resume`)
    },
    message: async (agent, text) => (await request<{ ok: boolean; id: string }>('POST', `${base}/agents/${enc(agent)}/message`, { text })).id,
    release: async (id) => (await request<{ ok: boolean }>('POST', `${base}/collisions/${enc(id)}/release`)).ok,
    stream: (since, { onEvent, onOpen, onError }) => {
      const es = new EventSource(`${base}/events/stream?since=${since}`)
      es.onopen = onOpen
      es.addEventListener('airspace', (m) => {
        try {
          onEvent(JSON.parse((m as MessageEvent<string>).data) as AirEvent)
        } catch {
          // A malformed frame is skipped; the next refetch catches up.
        }
      })
      es.onerror = () => {
        es.close()
        onError()
      }
      return () => es.close()
    },
  }
}

/** The server's own graph, as the demo Tower at /tower shows it. */
export const httpApi: TowerApi = createHttpApi('/api')

/** Event time as 10:42:31, local, 24 hour. */
export function clock(at: number) {
  return new Date(at * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

/** "utils.text.slugify" to "slugify", using the radar's label when it has one. */
export function shortName(qualname: string, symbols?: Record<string, RadarSymbol>) {
  const known = symbols?.[qualname]?.label
  if (known) return known
  const parts = qualname.split('.')
  return parts[parts.length - 1] || qualname
}
