import { AnimatePresence, motion } from 'motion/react'
import { useId } from 'react'
import { agents, byId, nodes, polar, RING, SCOPE_R, VIEW, type AgentKey, type ScopeNode } from './graph'

const ease = [0.22, 1, 0.36, 1] as const

function trimmed(a: ScopeNode, b: ScopeNode, ra: number, rb: number) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy)
  return `M${a.x + (dx / len) * ra} ${a.y + (dy / len) * ra} L${b.x - (dx / len) * rb} ${b.y - (dy / len) * rb}`
}

function Bezel({ agent, on }: { agent: AgentKey; on: boolean }) {
  const c = agents[agent]
  const ticks = []
  for (let d = 0; d < 360; d += 6) {
    const major = d % 30 === 0
    const p1 = polar(c.cx, c.cy, SCOPE_R, d)
    const p2 = polar(c.cx, c.cy, SCOPE_R + (major ? 11 : 5), d)
    ticks.push(<line key={d} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} strokeWidth={major ? 1.4 : 1} />)
  }
  const stroke = on ? c.color : 'var(--line-strong)'
  return (
    <g style={{ transition: 'opacity 600ms' }}>
      <circle cx={c.cx} cy={c.cy} r={SCOPE_R} fill={on ? c.soft : 'transparent'} stroke={stroke} strokeOpacity={on ? 0.75 : 1} strokeWidth={1.2} style={{ transition: 'fill 600ms, stroke 600ms' }} />
      <g stroke={stroke} strokeOpacity={on ? 0.6 : 0.8} style={{ transition: 'stroke 600ms' }}>
        {ticks}
      </g>
      {[RING[1], RING[2]].map((r, i) => (
        <circle key={r} cx={c.cx} cy={c.cy} r={r} fill="none" stroke={stroke} strokeOpacity={on ? 0.4 : 0.7} strokeDasharray={i === 0 ? '2 5' : undefined} strokeWidth={1} style={{ transition: 'stroke 600ms' }} />
      ))}
      <text x={c.cx} y={c.cy + RING[1] - 9} textAnchor="middle" className="scope-caps scope-hide-sm" fontSize={11.5} letterSpacing={1.4} fill="var(--faint)">
        1 HOP
      </text>
      <text x={c.cx} y={c.cy + RING[2] - 9} textAnchor="middle" className="scope-caps scope-hide-sm" fontSize={11.5} letterSpacing={1.4} fill="var(--faint)">
        2 HOPS
      </text>
      <text x={c.cx} y={c.cy - SCOPE_R - 40} textAnchor="middle" className="scope-caps scope-major" fontWeight={700} letterSpacing={1.8} fill={on ? c.color : 'var(--faint)'} style={{ transition: 'fill 600ms' }}>
        {c.id.toUpperCase()}
      </text>
      <text x={c.cx} y={c.cy - SCOPE_R - 19} textAnchor="middle" className="scope-caps scope-hide-sm" fontSize={13} letterSpacing={1.2} fill="var(--muted)">
        {c.task.toUpperCase()}
      </text>
    </g>
  )
}

function Label({ n, strong }: { n: ScopeNode; strong: boolean }) {
  if (n.hop === 0) {
    return (
      <text x={n.x} y={n.y + 42} textAnchor="middle" className="scope-major font-mono" fontWeight={700} fill="var(--text)">
        {n.label}
      </text>
    )
  }
  const out = polar(n.x, n.y, 14, n.angle)
  const cos = Math.cos((n.angle * Math.PI) / 180)
  const anchor = Math.abs(cos) < 0.2 ? 'middle' : cos > 0 ? 'start' : 'end'
  const dy = Math.abs(cos) < 0.2 ? (Math.sin((n.angle * Math.PI) / 180) > 0 ? 16 : -6) : 5
  return (
    <text x={out.x} y={out.y + dy} textAnchor={anchor} className="scope-minor font-mono" fill={strong ? 'var(--text)' : 'var(--muted)'} style={{ transition: 'fill 500ms' }}>
      {n.label}
    </text>
  )
}

export function Scope({ step, className = '' }: { step: number; className?: string }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const clip = `lensA${uid}`
  const clipB = `lensB${uid}`
  const on = { a: step >= 1, b: step >= 2 }
  const contract = step >= 4
  const held = step === 5 || step === 6
  const showCall = step >= 5
  const a = agents.a
  const b = agents.b
  const lensOpacity = step === 5 ? 0.92 : step === 6 ? 0.6 : 0
  const lensWord = step === 5 ? 'HOLD' : step === 6 ? 'BRIEFED' : step === 7 ? 'CLEARED' : null
  const slug = byId.slugify
  const render = byId.render_post

  return (
    <svg
      viewBox={`${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`}
      className={`block h-auto w-full ${className}`}
      role="img"
      aria-label="Two airspaces. agent-a is changing slugify; its range rings hold everything that calls it. agent-b is editing render_post. When agent-b's edit adds a call to slugify, the airspaces collide, the edit is held, agent-b is briefed with the new signature, then cleared."
    >
      <defs>
        <clipPath id={clip}>
          <circle cx={a.cx} cy={a.cy} r={SCOPE_R} />
        </clipPath>
        <clipPath id={clipB}>
          <circle cx={b.cx} cy={b.cy} r={SCOPE_R} />
        </clipPath>
      </defs>

      <Bezel agent="a" on={on.a} />
      <Bezel agent="b" on={on.b} />

      {/* The overlap. It fills the way the logo does when the airspaces collide. */}
      <circle cx={b.cx} cy={b.cy} r={SCOPE_R} fill="var(--accent)" clipPath={`url(#${clip})`} style={{ opacity: lensOpacity, transition: 'opacity 500ms cubic-bezier(0.22, 1, 0.36, 1)' }} />

      {/* Dependency edges, drawn from each node toward what it depends on. */}
      {nodes
        .filter((n) => n.parent)
        .map((n) => {
          const p = byId[n.parent!]
          const active = on[n.agent]
          return (
            <path
              key={n.id}
              d={trimmed(n, p, n.kind === 'test' ? 7 : 7, p.hop === 0 ? 18 : 8)}
              stroke={active ? agents[n.agent].color : 'var(--line-strong)'}
              strokeOpacity={active ? 0.7 : 1}
              strokeWidth={1.3}
              strokeDasharray={n.kind === 'test' ? '3 4' : undefined}
              style={{ transition: 'stroke 600ms' }}
            />
          )
        })}

      {/* The call agent-b's edit adds. */}
      <AnimatePresence>
        {showCall && (
          <motion.path
            key="call"
            d={trimmed(render, slug, 18, 20)}
            fill="none"
            strokeWidth={2.6}
            strokeLinecap="round"
            initial={{ pathLength: 0, stroke: 'var(--accent)' }}
            animate={{ pathLength: 1, stroke: step >= 7 ? 'var(--agent-b)' : 'var(--accent)' }}
            exit={{ opacity: 0, transition: { duration: 0.3 } }}
            transition={{ pathLength: { duration: 0.8, ease }, stroke: { duration: 0.4 } }}
          />
        )}
      </AnimatePresence>
      {held && (
        <g clipPath={`url(#${clip})`}>
          <path d={trimmed(render, slug, 18, 20)} stroke="var(--ink)" strokeWidth={2.6} clipPath={`url(#${clipB})`} />
        </g>
      )}

      {/* Nodes. */}
      {nodes.map((n) => {
        const active = on[n.agent]
        const color = active ? agents[n.agent].color : 'var(--faint)'
        if (n.hop === 0) {
          return (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r={15} fill="var(--bg)" stroke={color} strokeWidth={1.5} style={{ transition: 'stroke 500ms' }} />
              <circle cx={n.x} cy={n.y} r={7} fill={color} style={{ transition: 'fill 500ms' }} />
            </g>
          )
        }
        return n.kind === 'test' ? (
          <rect key={n.id} x={n.x - 5} y={n.y - 5} width={10} height={10} fill={color} style={{ transition: 'fill 500ms' }} />
        ) : (
          <circle key={n.id} cx={n.x} cy={n.y} r={5.5} fill={color} style={{ transition: 'fill 500ms' }} />
        )
      })}

      {contract && step < 7 && <circle cx={slug.x} cy={slug.y} r={21} fill="none" stroke="var(--accent)" strokeWidth={2} />}

      {nodes.map((n) => (
        <Label key={`l-${n.id}`} n={n} strong={on[n.agent]} />
      ))}

      {/* What the overlap says. */}
      <AnimatePresence mode="wait">
        {lensWord && (
          <motion.text
            key={lensWord}
            x={500}
            y={258}
            textAnchor="middle"
            className="scope-caps"
            fontSize={lensWord === 'HOLD' ? 24 : 15}
            fontWeight={700}
            letterSpacing={2}
            fill={lensWord === 'CLEARED' ? 'var(--ok)' : 'var(--ink)'}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease }}
          >
            {lensWord}
          </motion.text>
        )}
      </AnimatePresence>
    </svg>
  )
}
