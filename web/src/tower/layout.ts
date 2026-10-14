// Turns live radar data into a ScopeModel: where each airspace sits, where each
// symbol of its cone goes, and which labels fit without touching anything.

import { polar, RING, SCOPE_R, type ScopeAgent, type ScopeLens, type ScopeModel, type ScopeNode, type ScopeNote } from '../radar/graph'
import { shortName, type RadarData } from './api'

// ---------------------------------------------------------------- colours

export type AgentLook = { color: string; soft: string; letter: string }

const PALETTE = ['a', 'b', 'c', 'd'].map((k) => ({ color: `var(--agent-${k})`, soft: `var(--agent-${k}-soft)` }))

/** agent-a is cyan, agent-b violet, then green and amber. Stable for a set of ids. */
export function agentLooks(ids: string[]): Record<string, AgentLook> {
  const sorted = [...new Set(ids)].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
  return Object.fromEntries(sorted.map((id, i) => [id, { ...PALETTE[i % PALETTE.length], letter: letterOf(id) }]))
}

export function letterOf(id: string) {
  const tail = /[-_ ]([a-z0-9])$/i.exec(id)
  if (tail) return tail[1].toUpperCase()
  const first = /[a-z0-9]/i.exec(id)
  return first ? first[0].toUpperCase() : '?'
}

export const fallbackLook: AgentLook = { color: 'var(--muted)', soft: 'transparent', letter: '?' }

// ---------------------------------------------------------------- geometry

type Box = { x0: number; y0: number; x1: number; y1: number }
type Seg = { x0: number; y0: number; x1: number; y1: number }

const R = SCOPE_R
const OVERLAP = 310 // centre distance of two colliding airspaces, as in the hero
const APART = 2 * R + 130 // centre distance of two airspaces that do not collide
const ROW = 2 * R + 140
const MINOR_CH = 9.8 // JetBrains Mono at 16 units is 0.6em wide; a little slack
const MAJOR_CH = 11.2 // 18 units, semibold and bold
const MAX_LABEL = 20
const MAX_HOP1 = 8
const MAX_HOP2 = 6

const pad = (b: Box, p: number): Box => ({ x0: b.x0 - p, y0: b.y0 - p, x1: b.x1 + p, y1: b.y1 + p })
const hits = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

function boxHitsCircle(b: Box, cx: number, cy: number, r: number) {
  const x = Math.max(b.x0, Math.min(cx, b.x1))
  const y = Math.max(b.y0, Math.min(cy, b.y1))
  return Math.hypot(x - cx, y - cy) < r
}

/** Liang-Barsky: does the segment pass through the box? */
function segHitsBox(s: Seg, b: Box) {
  const dx = s.x1 - s.x0
  const dy = s.y1 - s.y0
  let t0 = 0
  let t1 = 1
  const tests: [number, number][] = [
    [-dx, s.x0 - b.x0],
    [dx, b.x1 - s.x0],
    [-dy, s.y0 - b.y0],
    [dy, b.y1 - s.y0],
  ]
  for (const [p, q] of tests) {
    if (p === 0) {
      if (q < 0) return false
      continue
    }
    const t = q / p
    if (p < 0) {
      if (t > t1) return false
      if (t > t0) t0 = t
    } else {
      if (t < t0) return false
      if (t < t1) t1 = t
    }
  }
  return true
}

function rectGap(a: Box, b: Box) {
  const dx = Math.max(0, a.x0 - b.x1, b.x0 - a.x1)
  const dy = Math.max(0, a.y0 - b.y1, b.y0 - a.y1)
  return Math.hypot(dx, dy)
}

function segsCross(a: Seg, b: Seg) {
  const o = (px: number, py: number, qx: number, qy: number, rx: number, ry: number) => (qx - px) * (ry - py) - (qy - py) * (rx - px)
  const d1 = o(a.x0, a.y0, a.x1, a.y1, b.x0, b.y0)
  const d2 = o(a.x0, a.y0, a.x1, a.y1, b.x1, b.y1)
  const d3 = o(b.x0, b.y0, b.x1, b.y1, a.x0, a.y0)
  const d4 = o(b.x0, b.y0, b.x1, b.y1, a.x1, a.y1)
  return d1 * d2 < 0 && d3 * d4 < 0
}

function trimmedSeg(a: { x: number; y: number }, b: { x: number; y: number }, ra: number, rb: number): Seg {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy) || 1
  return { x0: a.x + (dx / len) * ra, y0: a.y + (dy / len) * ra, x1: b.x - (dx / len) * rb, y1: b.y - (dy / len) * rb }
}

function clip(label: string, max: number) {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label
}

/** The box a cone label occupies, matching how Scope's Label anchors it. */
function minorLabelBox(x: number, y: number, angle: number, text: string): Box {
  const out = polar(x, y, 14, angle)
  const rad = (angle * Math.PI) / 180
  const cos = Math.cos(rad)
  const w = text.length * MINOR_CH
  const middle = Math.abs(cos) < 0.2
  const base = out.y + (middle ? (Math.sin(rad) > 0 ? 16 : -6) : 5)
  const x0 = middle ? out.x - w / 2 : cos > 0 ? out.x : out.x - w
  return { x0, y0: base - 13, x1: x0 + w, y1: base + 4 }
}

function majorBox(x: number, baseline: number, text: string): Box {
  const w = text.length * MAJOR_CH
  return { x0: x - w / 2, y0: baseline - 14, x1: x + w / 2, y1: baseline + 5 }
}

const norm = (deg: number) => ((((deg + 180) % 360) + 360) % 360) - 180
const angleDiff = (a: number, b: number) => norm(a - b)

// ---------------------------------------------------------------- layout

export type RadarLayout = {
  model: ScopeModel
  /** Cone symbols that did not fit, per agent id. */
  hidden: Record<string, number>
}

/**
 * Lays out up to four airspaces. Two sit side by side and overlap, like the hero.
 * Three or four sit in a grid and overlap only where a collision joins them.
 */
export function layoutRadar(
  radar: RadarData,
  looks: Record<string, AgentLook>,
  paused: Set<string>,
  opts: { onLens?: (id: string) => void; compact?: boolean } = {},
): RadarLayout {
  const { onLens, compact = false } = opts
  const collision = radar.collision
  let list = radar.agents.slice(0, 4)
  const owner = collision ? list.find((a) => a.id === collision.owner_agent) : undefined
  const held = collision ? list.find((a) => a.id === collision.held_agent) : undefined
  const paired = !!(owner && held && owner !== held)
  if (paired) list = [owner!, held!, ...list.filter((a) => a !== owner && a !== held)]

  // Centres.
  const n = list.length
  const centres: { x: number; y: number }[] = []
  if (n === 1) centres.push({ x: 0, y: 0 })
  else if (n === 2) centres.push({ x: 0, y: 0 }, { x: OVERLAP, y: 0 })
  else if (n > 2) {
    const top = paired ? OVERLAP : APART
    const mid = top / 2
    centres.push({ x: 0, y: 0 }, { x: top, y: 0 })
    if (n === 3) centres.push({ x: mid, y: ROW })
    else centres.push({ x: mid - APART / 2, y: ROW }, { x: mid + APART / 2, y: ROW })
  }
  const cx = centres.reduce((s, c) => s + c.x, 0) / Math.max(n, 1)
  const cy = centres.reduce((s, c) => s + c.y, 0) / Math.max(n, 1)

  const scopeAgents: ScopeAgent[] = list.map((a, i) => {
    const look = looks[a.id] ?? fallbackLook
    return { key: String.fromCharCode(97 + i), id: a.id, cx: centres[i].x, cy: centres[i].y, color: look.color, soft: look.soft, on: !paused.has(a.id) }
  })

  const boxes: Box[] = []
  const labelBoxes: Box[] = []
  const segs: Seg[] = []
  const nodes: ScopeNode[] = []
  const notes: ScopeNote[] = []
  const hidden: Record<string, number> = {}
  const extent: Box[] = []

  // Fixed furniture first: circles' names, centres, centre labels, the lens word, the call.
  scopeAgents.forEach((c) => {
    const idBox = majorBox(c.cx, c.cy - R - 22, c.id)
    boxes.push(idBox)
    extent.push(idBox, { x0: c.cx - R, y0: c.cy - R, x1: c.cx + R, y1: c.cy + R })
    // Room for a "+K more" note under the circle.
    boxes.push({ x0: c.cx - 60, y0: c.cy + R + 14, x1: c.cx + 60, y1: c.cy + R + 36 })
  })

  const lensWordY = (centres[0]?.y ?? 0) - 42
  const lensWordX = centres.length > 1 ? (centres[0].x + centres[1].x) / 2 : 0
  if (paired) {
    boxes.push({ x0: lensWordX - 50, y0: lensWordY - 26, x1: lensWordX + 50, y1: lensWordY + 8 })
    segs.push({ x0: centres[0].x, y0: centres[0].y, x1: centres[1].x, y1: centres[1].y })
  }

  const priority = new Set([collision?.symbol, collision?.caller].filter(Boolean) as string[])

  list.forEach((a, i) => {
    const c = scopeAgents[i]
    const center = a.center ?? a.claims[0] ?? null
    if (!center) {
      notes.push({ x: c.cx, y: c.cy + 6, text: 'No plan yet' })
      return
    }
    const id = `${c.key}:${center}`
    const label = clip(shortName(center, radar.symbols), 18)
    nodes.push({ id, label, qualname: center, kind: radar.symbols[center]?.is_test ? 'test' : 'fn', agent: c.key, hop: 0, angle: 0, x: c.cx, y: c.cy })
    boxes.push({ x0: c.cx - 18, y0: c.cy - 18, x1: c.cx + 18, y1: c.cy + 18 })
    const lb = majorBox(c.cx, c.cy + 42, label)
    boxes.push(lb)
    labelBoxes.push(lb)
  })

  const outward = (i: number) => {
    if (n === 1) return 180
    const c = centres[i]
    return (Math.atan2(c.y - cy, c.x - cx) * 180) / Math.PI
  }
  const halfSector = n === 1 ? 180 : n === 2 ? 100 : 115

  const fits = (agentIndex: number, x: number, y: number, label: Box, edge: Seg | null) => {
    for (let j = 0; j < n; j++) {
      if (j === agentIndex) continue
      const o = centres[j]
      if (Math.hypot(x - o.x, y - o.y) < R + 14) return false
      if (boxHitsCircle(label, o.x, o.y, R + 2)) return false
    }
    const node: Box = { x0: x - 9, y0: y - 9, x1: x + 9, y1: y + 9 }
    const padded = pad(label, 3)
    for (const b of boxes) if (hits(node, b) || hits(padded, b)) return false
    for (const s of segs) if (segHitsBox(s, padded)) return false
    if (edge) for (const b of labelBoxes) if (segHitsBox(edge, b)) return false
    return true
  }

  type Want = { qualname: string; target: number; parent?: ScopeNode; range: number }

  // Among the angles near the target that fit, take the one with the most room
  // around it and no crossed edges, so labels spread out instead of packing.
  const place = (agentIndex: number, hop: 1 | 2, want: Want) => {
    const c = scopeAgents[agentIndex]
    const text = clip(shortName(want.qualname, radar.symbols), MAX_LABEL)
    const parent = want.parent ?? (hop === 1 ? nodes.find((m) => m.agent === c.key && m.hop === 0) : undefined)
    let best: { score: number; angle: number; p: { x: number; y: number }; label: Box; edge: Seg | null } | null = null
    for (let k = 0; k <= (want.range / 4) * 2; k++) {
      const offset = (k % 2 === 1 ? 1 : -1) * Math.ceil(k / 2) * 4
      const angle = norm(want.target + offset)
      if (n > 1 && Math.abs(angleDiff(angle, outward(agentIndex))) > halfSector + 30) continue
      const p = polar(c.cx, c.cy, RING[hop], angle)
      const label = minorLabelBox(p.x, p.y, angle, text)
      const edge = parent ? trimmedSeg(p, parent, 7, parent.hop === 0 ? 18 : 8) : null
      if (!fits(agentIndex, p.x, p.y, label, edge)) continue
      const node: Box = { x0: p.x - 9, y0: p.y - 9, x1: p.x + 9, y1: p.y + 9 }
      let room = 28
      for (const b of boxes) room = Math.min(room, rectGap(label, b), rectGap(node, b))
      const crossings = edge ? segs.filter((s) => segsCross(s, edge)).length : 0
      const score = room - 0.25 * Math.abs(offset) - 30 * crossings
      if (!best || score > best.score) best = { score, angle, p, label, edge }
    }
    if (best) {
      const { angle, p, label, edge } = best
      const node: ScopeNode = {
        id: `${c.key}:${want.qualname}`,
        label: text,
        qualname: want.qualname,
        kind: radar.symbols[want.qualname]?.is_test ? 'test' : 'fn',
        agent: c.key,
        hop,
        angle,
        parent: parent?.id,
        x: p.x,
        y: p.y,
      }
      nodes.push(node)
      boxes.push({ x0: p.x - 9, y0: p.y - 9, x1: p.x + 9, y1: p.y + 9 }, label)
      labelBoxes.push(label)
      if (edge) segs.push(edge)
      // On phones the cone labels are hidden, so they do not widen the view.
      if (!compact) extent.push(label)
      return node
    }
    return null
  }

  const adjacency = new Map<string, Set<string>>()
  for (const [x, y] of radar.edges) {
    if (!adjacency.has(x)) adjacency.set(x, new Set())
    if (!adjacency.has(y)) adjacency.set(y, new Set())
    adjacency.get(x)!.add(y)
    adjacency.get(y)!.add(x)
  }

  // Cones, ring 1 for every agent first, then ring 2, so no agent crowds out another.
  const cones = list.map((a) => {
    const center = a.center ?? a.claims[0] ?? null
    const seen = new Set<string>(center ? [center] : [])
    const cone = a.cone.filter((s) => (seen.has(s.qualname) ? false : (seen.add(s.qualname), true)))
    const rank = (q: string) => (priority.has(q) ? 0 : 1)
    const ordered = [...cone].sort((x, y) => rank(x.qualname) - rank(y.qualname))
    const hop1 = center ? ordered.filter((s) => s.hop <= 1) : []
    const hop2 = center ? ordered.filter((s) => s.hop >= 2) : []
    return { hop1, hop2, total: center ? cone.length : 0 }
  })

  const placed: number[] = list.map(() => 0)

  cones.forEach(({ hop1 }, i) => {
    const take = hop1.slice(0, MAX_HOP1)
    const k = take.length
    const spread = n === 1 ? 360 / Math.max(k, 1) : Math.min(60, (2 * halfSector) / Math.max(k, 1))
    take.forEach((s, j) => {
      const target = outward(i) + (j - (k - 1) / 2) * spread
      if (place(i, 1, { qualname: s.qualname, target, range: 60 })) placed[i] += 1
    })
  })

  cones.forEach(({ hop2 }, i) => {
    const c = scopeAgents[i]
    const ring1 = nodes.filter((m) => m.agent === c.key && m.hop === 1)
    const byParent = new Map<ScopeNode | undefined, string[]>()
    for (const s of hop2.slice(0, MAX_HOP2 + 4)) {
      const near = adjacency.get(s.qualname)
      const parent = ring1.find((m) => near?.has(m.qualname))
      // A ring 2 symbol whose ring 1 neighbour is not drawn would float; count it instead.
      if (!parent && near && [...near].some((q) => cones[i].hop1.some((h) => h.qualname === q))) continue
      if (!byParent.has(parent)) byParent.set(parent, [])
      byParent.get(parent)!.push(s.qualname)
    }
    let budget = MAX_HOP2
    for (const [parent, qs] of byParent) {
      const m = qs.length
      qs.forEach((q, j) => {
        if (budget <= 0) return
        let target: number
        if (parent) {
          const lean = Math.max(-35, Math.min(35, angleDiff(outward(i), parent.angle) * 0.5))
          target = parent.angle + lean + (j - (m - 1) / 2) * 22
        } else {
          target = outward(i) + (j - (m - 1) / 2) * 30
        }
        if (place(i, 2, { qualname: q, target, parent, range: parent ? 40 : 60 })) {
          placed[i] += 1
          budget -= 1
        }
      })
    }
  })

  list.forEach((a, i) => {
    const c = scopeAgents[i]
    const rest = cones[i].total - placed[i]
    hidden[a.id] = rest
    if (rest > 0) {
      const note = { x: c.cx, y: c.cy + R + 30, text: `+${rest} more` }
      notes.push(note)
      if (!compact) extent.push({ x0: c.cx - 50, y0: c.cy + R + 14, x1: c.cx + 50, y1: c.cy + R + 36 })
    }
  })

  // The lens and the call.
  let lens: ScopeLens | undefined
  let call: ScopeModel['call']
  let ring: string | undefined
  if (paired && collision) {
    const [ka, kb] = [scopeAgents[0].key, scopeAgents[1].key]
    const res = collision.resolution
    lens = {
      a: ka,
      b: kb,
      opacity: res === 'held' ? 0.92 : res === 'released' ? 0.22 : 0,
      word: res === 'held' ? 'Hold' : res === 'released' ? 'Released' : 'Cleared',
      wordColor: res === 'released' ? 'var(--text)' : undefined,
      wordX: lensWordX,
      wordY: lensWordY,
      onClick: onLens ? () => onLens(collision.id) : undefined,
      title: `Open the collision at ${shortName(collision.symbol, radar.symbols)}`,
    }
    const find = (key: string, q: string | null) => (q ? nodes.find((m) => m.agent === key && m.qualname === q) : undefined)
    const from = find(kb, collision.caller) ?? nodes.find((m) => m.agent === kb && m.hop === 0)
    const to = find(ka, collision.symbol) ?? nodes.find((m) => m.agent === ka && m.hop === 0)
    if (from && to) {
      call = { from: from.id, to: to.id, color: res === 'held' ? 'var(--accent)' : scopeAgents[1].color, held: res === 'held' }
      if (res === 'held') ring = to.id
    }
  }

  // Fit the view to what was drawn.
  const all = extent.length ? extent : [{ x0: -R, y0: -R, x1: R, y1: R }]
  const x0 = Math.min(...all.map((b) => b.x0)) - 20
  const y0 = Math.min(...all.map((b) => b.y0)) - 16
  const x1 = Math.max(...all.map((b) => b.x1)) + 20
  const y1 = Math.max(...all.map((b) => b.y1)) + 16

  return {
    model: { view: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }, agents: scopeAgents, nodes, lens, call, ring, notes },
    hidden,
  }
}
