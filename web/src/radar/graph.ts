// A small slice of a Django blog project, laid out as two airspaces.
// Each agent's airspace is centred on the symbol it claims. Ring 1 holds
// everything one call away, ring 2 everything two calls away: the impact cone.
//
// The scope itself draws a ScopeModel. The marketing story builds one from a
// step number (demoModel); Tower builds one from live radar data.

export type AgentKey = 'a' | 'b'
export type NodeKind = 'fn' | 'test'

// The drawing area actually used, so the scope renders as large as possible.
export const VIEW = { x: 20, y: 46, w: 910, h: 480 }
export const RING = [0, 104, 186] as const
export const SCOPE_R = 206

export type ScopeView = { x: number; y: number; w: number; h: number }

/** One airspace: a circle centred on what the agent claims. */
export type ScopeAgent = {
  key: string
  id: string
  cx: number
  cy: number
  color: string
  soft: string
  /** Lit in the agent's colour, or drawn quiet (not started, or paused). */
  on: boolean
}

export const agents = {
  a: { key: 'a' as const, id: 'agent-a', task: 'Refactor slugify', claim: 'slugify', cx: 345, cy: 300, color: 'var(--agent-a)', soft: 'var(--agent-a-soft)' },
  b: { key: 'b' as const, id: 'agent-b', task: 'Permalinks in posts', claim: 'render_post', cx: 655, cy: 300, color: 'var(--agent-b)', soft: 'var(--agent-b-soft)' },
}

export type ScopeNode = {
  id: string
  label: string
  qualname: string
  kind: NodeKind
  /** Key of the airspace the node belongs to. */
  agent: string
  hop: 0 | 1 | 2
  angle: number // degrees, 0 = east, clockwise
  parent?: string
  x: number
  y: number
}

/** The overlap of two airspaces. It fills orange when they collide. */
export type ScopeLens = {
  a: string
  b: string
  opacity: number
  word: string | null
  wordX: number
  wordY: number
  /** Defaults to ink on orange, or green for Cleared. */
  wordColor?: string
  /** Live only: the lens becomes a button. */
  onClick?: () => void
  title?: string
}

/** The call one agent's edit adds into another agent's airspace. */
export type ScopeCall = {
  from: string
  to: string
  color: string
  /** Darken the part of the call inside the lens, so it reads on orange. */
  held: boolean
}

/** Extra words in the scope, such as "+3 more" under a crowded airspace. */
export type ScopeNote = { x: number; y: number; text: string }

export type ScopeModel = {
  view: ScopeView
  agents: ScopeAgent[]
  nodes: ScopeNode[]
  lens?: ScopeLens
  call?: ScopeCall
  /** Node with an orange ring: its contract is changing. */
  ring?: string
  notes?: ScopeNote[]
}

const raw: Omit<ScopeNode, 'x' | 'y'>[] = [
  { id: 'slugify', label: 'slugify', qualname: 'utils.text.slugify', kind: 'fn', agent: 'a', hop: 0, angle: 0 },
  { id: 'post_save', label: 'Post.save', qualname: 'blog.models.Post.save', kind: 'fn', agent: 'a', hop: 1, angle: -120, parent: 'slugify' },
  { id: 'test_slugify', label: 'test_slugify', qualname: 'tests.test_text.test_slugify', kind: 'test', agent: 'a', hop: 1, angle: 180, parent: 'slugify' },
  { id: 'tag_save', label: 'Tag.save', qualname: 'tags.models.Tag.save', kind: 'fn', agent: 'a', hop: 1, angle: 120, parent: 'slugify' },
  { id: 'test_post_save', label: 'test_post_save', qualname: 'tests.test_models.test_post_save', kind: 'test', agent: 'a', hop: 2, angle: -158, parent: 'post_save' },
  { id: 'tag_create', label: 'tag_create', qualname: 'tags.views.tag_create', kind: 'fn', agent: 'a', hop: 2, angle: 158, parent: 'tag_save' },
  { id: 'render_post', label: 'render_post', qualname: 'blog.views.render_post', kind: 'fn', agent: 'b', hop: 0, angle: 0 },
  { id: 'post_list', label: 'post_list', qualname: 'blog.views.post_list', kind: 'fn', agent: 'b', hop: 1, angle: -60, parent: 'render_post' },
  { id: 'test_render', label: 'test_render_post', qualname: 'tests.test_views.test_render_post', kind: 'test', agent: 'b', hop: 1, angle: 0, parent: 'render_post' },
  { id: 'item_desc', label: 'item_description', qualname: 'blog.feeds.LatestPosts.item_description', kind: 'fn', agent: 'b', hop: 1, angle: 60, parent: 'render_post' },
  { id: 'feed_view', label: 'LatestPosts', qualname: 'blog.feeds.LatestPosts', kind: 'fn', agent: 'b', hop: 2, angle: 70, parent: 'item_desc' },
]

export function polar(cx: number, cy: number, r: number, deg: number) {
  const rad = (deg * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

export const nodes: ScopeNode[] = raw.map((n) => {
  const c = agents[n.agent as AgentKey]
  const p = polar(c.cx, c.cy, RING[n.hop], n.angle)
  return { ...n, ...p }
})

export const byId = Object.fromEntries(nodes.map((n) => [n.id, n])) as Record<string, ScopeNode>

/** The marketing story at a step: what is lit, held, briefed or cleared. */
export function demoModel(step: number): ScopeModel {
  const lensOpacity = step === 5 ? 0.92 : step === 6 ? 0.6 : 0
  const lensWord = step === 5 ? 'Hold' : step === 6 ? 'Briefed' : step === 7 ? 'Cleared' : null
  return {
    view: VIEW,
    agents: [
      { ...agents.a, on: step >= 1 },
      { ...agents.b, on: step >= 2 },
    ],
    nodes,
    lens: { a: 'a', b: 'b', opacity: lensOpacity, word: lensWord, wordX: 500, wordY: 258 },
    call: step >= 5 ? { from: 'render_post', to: 'slugify', color: step >= 7 ? 'var(--agent-b)' : 'var(--accent)', held: step === 5 || step === 6 } : undefined,
    ring: step >= 4 && step < 7 ? 'slugify' : undefined,
  }
}
