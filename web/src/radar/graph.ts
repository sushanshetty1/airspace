// A small slice of a Django blog project, laid out as two airspaces.
// Each agent's airspace is centred on the symbol it claims. Ring 1 holds
// everything one call away, ring 2 everything two calls away: the impact cone.

export type AgentKey = 'a' | 'b'
export type NodeKind = 'fn' | 'test'

// The drawing area actually used, so the scope renders as large as possible.
export const VIEW = { x: 20, y: 28, w: 910, h: 500 }
export const RING = [0, 104, 186] as const
export const SCOPE_R = 206

export const agents = {
  a: { key: 'a' as const, id: 'agent-a', task: 'Refactor slugify', claim: 'slugify', cx: 345, cy: 300, color: 'var(--agent-a)', soft: 'var(--agent-a-soft)' },
  b: { key: 'b' as const, id: 'agent-b', task: 'Permalinks in posts', claim: 'render_post', cx: 655, cy: 300, color: 'var(--agent-b)', soft: 'var(--agent-b-soft)' },
}

export type ScopeNode = {
  id: string
  label: string
  qualname: string
  kind: NodeKind
  agent: AgentKey
  hop: 0 | 1 | 2
  angle: number // degrees, 0 = east, clockwise
  parent?: string
  x: number
  y: number
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
  const c = agents[n.agent]
  const p = polar(c.cx, c.cy, RING[n.hop], n.angle)
  return { ...n, ...p }
})

export const byId = Object.fromEntries(nodes.map((n) => [n.id, n])) as Record<string, ScopeNode>
