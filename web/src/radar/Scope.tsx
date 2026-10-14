import { AnimatePresence, motion } from 'motion/react'
import { useId, type CSSProperties } from 'react'
import { demoModel, polar, RING, SCOPE_R, type ScopeAgent, type ScopeModel, type ScopeNode } from './graph'

const ease = [0.22, 1, 0.36, 1] as const

const DEMO_LABEL =
  "Two airspaces. agent-a is changing slugify; its range rings hold everything that calls it. agent-b is editing render_post. When agent-b's edit adds a call to slugify, the airspaces collide, the edit is held, agent-b is briefed with the new signature, then cleared."

function trimmed(a: ScopeNode, b: ScopeNode, ra: number, rb: number) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len = Math.hypot(dx, dy)
  return `M${a.x + (dx / len) * ra} ${a.y + (dy / len) * ra} L${b.x - (dx / len) * rb} ${b.y - (dy / len) * rb}`
}

function Airspace({ c }: { c: ScopeAgent }) {
  const on = c.on
  const stroke = on ? c.color : 'var(--line-strong)'
  return (
    <g>
      <circle cx={c.cx} cy={c.cy} r={SCOPE_R} fill={on ? c.soft : 'transparent'} stroke={stroke} strokeOpacity={on ? 0.6 : 1} strokeWidth={1.2} style={{ transition: 'fill 600ms, stroke 600ms' }} />
      <circle cx={c.cx} cy={c.cy} r={RING[1]} fill="none" stroke={stroke} strokeOpacity={on ? 0.3 : 0.6} strokeDasharray="2 6" strokeWidth={1} style={{ transition: 'stroke 600ms' }} />
      <text x={c.cx} y={c.cy - SCOPE_R - 22} textAnchor="middle" className="scope-major font-mono" fontWeight={600} fill={on ? c.color : 'var(--faint)'} style={{ transition: 'fill 600ms' }}>
        {c.id}
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

/** Draws any set of airspaces: the marketing story or live radar data. */
export function ScopeView({ model, className = '', label = DEMO_LABEL, style }: { model: ScopeModel; className?: string; label?: string; style?: CSSProperties }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const clipId = (key: string) => `lens${key.toUpperCase()}${uid}`
  const { view, lens, call } = model
  const byKey = Object.fromEntries(model.agents.map((a) => [a.key, a]))
  const byId = Object.fromEntries(model.nodes.map((n) => [n.id, n]))
  const on = (key: string) => byKey[key]?.on ?? false
  const la = lens ? byKey[lens.a] : undefined
  const lb = lens ? byKey[lens.b] : undefined
  const from = call ? byId[call.from] : undefined
  const to = call ? byId[call.to] : undefined
  const callPath = from && to ? trimmed(from, to, from.hop === 0 ? 18 : 9, to.hop === 0 ? 20 : 9) : null
  const ringNode = model.ring ? byId[model.ring] : undefined

  return (
    <svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} className={`block h-auto w-full ${className}`} role="img" aria-label={label} style={style}>
      {la && lb && (
        <defs>
          <clipPath id={clipId(la.key)}>
            <circle cx={la.cx} cy={la.cy} r={SCOPE_R} />
          </clipPath>
          <clipPath id={clipId(lb.key)}>
            <circle cx={lb.cx} cy={lb.cy} r={SCOPE_R} />
          </clipPath>
        </defs>
      )}

      {model.agents.map((c) => (
        <Airspace key={c.key} c={c} />
      ))}

      {/* The overlap. It fills the way the logo does when the airspaces collide. */}
      {lens && la && lb && (
        <circle cx={lb.cx} cy={lb.cy} r={SCOPE_R} fill="var(--accent)" clipPath={`url(#${clipId(la.key)})`} style={{ opacity: lens.opacity, transition: 'opacity 500ms cubic-bezier(0.22, 1, 0.36, 1)' }} />
      )}

      {/* Dependency edges, drawn from each node toward what it depends on. */}
      {model.nodes
        .filter((n) => n.parent && byId[n.parent])
        .map((n) => {
          const p = byId[n.parent!]
          const active = on(n.agent)
          return (
            <path
              key={n.id}
              d={trimmed(n, p, n.kind === 'test' ? 7 : 7, p.hop === 0 ? 18 : 8)}
              stroke={active ? byKey[n.agent].color : 'var(--line-strong)'}
              strokeOpacity={active ? 0.7 : 1}
              strokeWidth={1.3}
              strokeDasharray={n.kind === 'test' ? '3 4' : undefined}
              style={{ transition: 'stroke 600ms' }}
            />
          )
        })}

      {/* The call the held agent's edit adds. */}
      <AnimatePresence>
        {callPath && call && (
          <motion.path
            key="call"
            d={callPath}
            fill="none"
            strokeWidth={2.6}
            strokeLinecap="round"
            initial={{ pathLength: 0, stroke: 'var(--accent)' }}
            animate={{ pathLength: 1, stroke: call.color }}
            exit={{ opacity: 0, transition: { duration: 0.3 } }}
            transition={{ pathLength: { duration: 0.8, ease }, stroke: { duration: 0.4 } }}
          />
        )}
      </AnimatePresence>
      {callPath && call?.held && la && lb && (
        <g clipPath={`url(#${clipId(la.key)})`}>
          <path d={callPath} stroke="var(--ink)" strokeWidth={2.6} clipPath={`url(#${clipId(lb.key)})`} />
        </g>
      )}

      {/* Nodes. */}
      {model.nodes.map((n) => {
        const active = on(n.agent)
        const color = active ? byKey[n.agent].color : 'var(--faint)'
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

      {ringNode && <circle cx={ringNode.x} cy={ringNode.y} r={21} fill="none" stroke="var(--accent)" strokeWidth={2} />}

      {model.nodes.map((n) => (
        <Label key={`l-${n.id}`} n={n} strong={on(n.agent)} />
      ))}

      {model.notes?.map((t) => (
        <text key={`n-${t.x}-${t.y}`} x={t.x} y={t.y} textAnchor="middle" className="scope-minor" fill="var(--muted)">
          {t.text}
        </text>
      ))}

      {/* What the overlap says. */}
      <AnimatePresence mode="wait">
        {lens?.word && (
          <motion.text
            key={lens.word}
            x={lens.wordX}
            y={lens.wordY}
            textAnchor="middle"
            fontSize={lens.word === 'Hold' ? 26 : 17}
            fontWeight={650}
            letterSpacing={-0.3}
            fill={lens.wordColor ?? (lens.word === 'Cleared' ? 'var(--ok)' : 'var(--ink)')}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease }}
          >
            {lens.word}
          </motion.text>
        )}
      </AnimatePresence>

      {/* Live only: the lens opens the collision. */}
      {lens?.onClick && la && lb && (
        <circle
          cx={lb.cx}
          cy={lb.cy}
          r={SCOPE_R}
          fill="transparent"
          clipPath={`url(#${clipId(la.key)})`}
          role="button"
          tabIndex={0}
          aria-label={lens.title}
          strokeWidth={3}
          className="cursor-pointer outline-none focus-visible:stroke-text"
          onClick={lens.onClick}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              lens.onClick?.()
            }
          }}
        >
          {lens.title && <title>{lens.title}</title>}
        </circle>
      )}
    </svg>
  )
}

/** The marketing scope at a step of the story. */
export function Scope({ step, className = '' }: { step: number; className?: string }) {
  return <ScopeView model={demoModel(step)} className={className} />
}
