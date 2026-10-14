// Typed client for `airspace serve`. Shapes follow the Phase 2 contract
// (docs/superpowers/plans/2026-10-14-phase-2-tower-mcp-memory.md).

export type Resolution = 'held' | 'released' | 'resolved'

export type EventKind = 'plan' | 'cleared' | 'hold' | 'briefed' | 'contract' | 'paused' | 'resumed' | 'released' | 'message' | 'resolved' | 'noted'

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
  /** The memory plan stores the held call and the call it cleared with; older servers leave them out. */
  held_call?: string | null
  fixed_call?: string | null
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

/** What the graph remembers about a symbol: a note, the fix written when a collision cleared, or a contract change. */
export type MemoryKind = 'note' | 'fix' | 'contract'

export type MemoryItem = {
  id: string
  kind: MemoryKind
  symbol: string
  text: string
  agent: string
  at: number
  /** Not in the contract; matches a fix to its collision when the server sends it. */
  collision?: string | null
}

export const NOTE_MAX = 500

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
  /** Newest notes and fixes. null when the server has no memory (it answers 404). */
  recentMemory(limit?: number): Promise<MemoryItem[] | null>
  /** What the graph remembers about these symbols, newest first. null when the server has no memory. */
  memory(symbols: string[]): Promise<MemoryItem[] | null>
  /** Writes a note from Tower about these symbols; returns its id. */
  addNote(symbols: string[], text: string): Promise<string>
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
    throw new ApiError(res.status, errorText(data) || `The server answered ${res.status}.`)
  }
  return data as T
}

/** The message in an error body: `{"error"}`, `{"detail": "..."}`, or FastAPI's list of validation errors. */
function errorText(data: unknown): string {
  const body = (data ?? {}) as { error?: unknown; detail?: unknown }
  if (typeof body.error === 'string') return body.error
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    const first = body.detail[0] as { msg?: unknown } | undefined
    if (first && typeof first.msg === 'string') return first.msg.replace(/^Value error, /, '')
  }
  return ''
}

/** The items of a memory answer, keeping only well formed ones. */
function memoryList(data: unknown): MemoryItem[] {
  const items = (data as { items?: unknown } | null)?.items
  if (!Array.isArray(items)) return []
  return items.filter(
    (i): i is MemoryItem => !!i && typeof i === 'object' && typeof i.id === 'string' && typeof i.text === 'string' && typeof i.symbol === 'string' && typeof i.at === 'number',
  )
}

/** A GET where 404 means the server predates the route: null. */
async function optional<T>(path: string): Promise<T | null> {
  try {
    return await request<T>('GET', path)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
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
    recentMemory: async (limit = 20) => {
      const data = await optional(`${base}/memory/recent?limit=${limit}`)
      return data === null ? null : memoryList(data)
    },
    memory: async (symbols) => {
      const data = await optional(`${base}/memory?symbols=${symbols.map(enc).join(',')}`)
      return data === null ? null : memoryList(data)
    },
    addNote: async (symbols, text) => {
      const res = await request<{ id?: unknown; ok?: boolean; error?: unknown } | null>('POST', `${base}/notes`, { symbols, text })
      // Tower's controls report a refusal as ok: false with a reason; a note may too.
      if (!res || res.ok === false || typeof res.id !== 'string') throw new ApiError(422, typeof res?.error === 'string' ? res.error : 'The note was not saved.')
      return res.id
    },
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

/** An epoch time as "just now", "4 min ago", "3 h ago", "yesterday" or "Oct 14". */
export function ago(at: number, now = Date.now() / 1000) {
  const s = Math.max(0, now - at)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`
  const then = new Date(at * 1000)
  const today = new Date(now * 1000)
  if (s < 86400 && then.getDate() === today.getDate()) return `${Math.round(s / 3600)} h ago`
  const yesterday = new Date(now * 1000)
  yesterday.setDate(yesterday.getDate() - 1)
  if (then.toDateString() === yesterday.toDateString()) return 'yesterday'
  return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/**
 * The fix note for a resolved collision: the one that names the collision when the server says so,
 * otherwise the earliest fix about its symbol written after the hold, preferring one that names the held agent.
 */
export function fixFor(c: Pick<CollisionDetail, 'id' | 'symbol' | 'at' | 'held_agent'>, items: MemoryItem[]): MemoryItem | null {
  const fixes = items.filter((i) => i.kind === 'fix')
  const named = fixes.find((i) => i.collision === c.id)
  if (named) return named
  const after = fixes.filter((i) => !i.collision && i.symbol === c.symbol && i.at >= c.at - 1).sort((a, b) => a.at - b.at)
  return after.find((i) => i.text.includes(c.held_agent)) ?? after[0] ?? null
}

/** "utils.text.slugify" to "slugify", using the radar's label when it has one. */
export function shortName(qualname: string, symbols?: Record<string, RadarSymbol>) {
  const known = symbols?.[qualname]?.label
  if (known) return known
  const parts = qualname.split('.')
  return parts[parts.length - 1] || qualname
}
