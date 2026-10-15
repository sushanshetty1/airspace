import type { CSSProperties, ReactNode } from 'react'
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { C, H, MONO, SANS, W, ease } from '../brand'

export const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const

/** Seconds since the start of the current Sequence. */
export function useSec() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return { sec: frame / fps, fps, frame }
}

/** 0 to 1 along the site's ease, from `at` for `dur` seconds. */
export const ramp = (sec: number, at: number, dur = 0.5, easing = ease) => interpolate(sec, [at, at + dur], [0, 1], { ...clamp, easing })

/** A settled spring from `at`. */
export const pop = (sec: number, at: number, fps: number, config = { damping: 20, stiffness: 140, mass: 0.9 }) =>
  sec < at ? 0 : spring({ frame: (sec - at) * fps, fps, config })

/** The radar the whole film sits on: range rings, a crosshair and a slow sweep, barely there. */
export function Backdrop({ t }: { t: number }) {
  const angle = (t * 22) % 360
  return (
    <div style={{ position: 'absolute', inset: 0, background: C.deep, overflow: 'hidden' }}>
      <div
        style={{
          position: 'absolute',
          left: W / 2 - 1400,
          top: H / 2 - 1400,
          width: 2800,
          height: 2800,
          borderRadius: '50%',
          background: `conic-gradient(from ${angle}deg, rgba(69,196,230,0.028) 0deg, rgba(69,196,230,0.0) 38deg, transparent 360deg)`,
        }}
      />
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0 }}>
        {[200, 400, 600, 800, 1000].map((r) => (
          <circle key={r} cx={W / 2} cy={H / 2} r={r} fill="none" stroke="rgba(237,239,241,0.045)" strokeWidth={1} />
        ))}
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="rgba(237,239,241,0.03)" />
        <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="rgba(237,239,241,0.03)" />
      </svg>
    </div>
  )
}

/** Two airspaces; the orange lens is where they meet. `p` closes them together, `lens` fills the overlap. */
export function LogoMark({ size = 40, color = C.text, p = 1, lens = 1 }: { size?: number; color?: string; p?: number; lens?: number }) {
  const d = 46 * p
  const id = `lg${Math.round(size)}`
  return (
    <svg viewBox="0 0 150 104" height={size} width={(size * 150) / 104} style={{ overflow: 'visible' }}>
      <defs>
        <clipPath id={id}>
          <circle cx={75 - d / 2} cy="52" r="46" />
        </clipPath>
      </defs>
      <circle cx={75 + d / 2} cy="52" r="46" fill={C.accent} clipPath={`url(#${id})`} opacity={lens} />
      <circle cx={75 - d / 2} cy="52" r="42" fill="none" stroke={color} strokeWidth="9" />
      <circle cx={75 + d / 2} cy="52" r="42" fill="none" stroke={color} strokeWidth="9" />
    </svg>
  )
}

export function Wordmark({ size = 34, color = C.text }: { size?: number; color?: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.36 }}>
      <LogoMark size={size * 0.82} color={color} />
      <span style={{ fontFamily: SANS, fontWeight: 600, fontSize: size, letterSpacing: '-0.02em', color }}>Airspace</span>
    </span>
  )
}

/** A card the way the product draws a window: one hairline, a title bar. */
export function Panel({ title, right, children, style }: { title?: ReactNode; right?: ReactNode; children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        background: C.surface,
        borderRadius: 14,
        boxShadow: `0 30px 80px -30px rgba(0,0,0,0.85), inset 0 0 0 1px ${C.line}`,
        overflow: 'hidden',
        ...style,
      }}
    >
      {title && (
        <div style={{ height: 46, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 18px', borderBottom: `1px solid ${C.line}`, fontFamily: SANS, fontSize: 16, color: C.text }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>{title}</div>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

const KEYWORDS = /\b(MATCH|OPTIONAL|WHERE|RETURN|MERGE|WITH|AND|IN|LIMIT|SET|AS|ON|CREATE)\b/

/** Cypher, lightly set: keywords bright, labels and relationships quiet, parameters green. */
export function Cypher({ code, size = 17, dim = 0 }: { code: string; size?: number; dim?: number }) {
  const lines = code.split('\n')
  return (
    <pre style={{ margin: 0, fontFamily: MONO, fontSize: size, lineHeight: 1.65, color: C.muted, whiteSpace: 'pre', fontVariantLigatures: 'none' }}>
      {lines.map((line, i) => {
        if (line.trim().startsWith('//'))
          return (
            <div key={i} style={{ color: C.faint }}>
              {line}
            </div>
          )
        const parts = line.split(/(\$\w+|:[A-Z][A-Za-z|]+|\b[A-Z]{2,}\b|'[^']*')/g)
        return (
          <div key={i} style={{ opacity: 1 - dim }}>
            {parts.map((p, k) => {
              if (KEYWORDS.test(p) && /^[A-Z]+$/.test(p)) return <span key={k} style={{ color: C.text, fontWeight: 600 }}>{p}</span>
              if (p.startsWith('$')) return <span key={k} style={{ color: C.ok }}>{p}</span>
              if (p.startsWith(':')) return <span key={k} style={{ color: '#c9ced3' }}>{p}</span>
              if (p.startsWith("'")) return <span key={k} style={{ color: '#e8c48a' }}>{p}</span>
              return <span key={k}>{p}</span>
            })}
          </div>
        )
      })}
    </pre>
  )
}

export type TermLine = {
  at: number
  /**
   * prompt  the user's prompt, typed            cmd     a shell command, typed
   * tool    a tool call, `● Update(path)`        add/del a diff line
   * status  the `⎿` line under a tool call       body    hook or tool output, indented under it
   * say     the agent's own message, `● ...`     out     plain output
   */
  kind: 'prompt' | 'cmd' | 'tool' | 'add' | 'del' | 'status' | 'body' | 'say' | 'out'
  text: string
  /** Characters per second for typed lines (prompt and cmd). */
  cps?: number
  /** status: the colour of the line (a hook that blocked is muted red). */
  color?: string
  /** body: words coloured as a terminal colours them. */
  tokens?: { text: string; color: string; bold?: boolean }[]
  /** body: words a highlight sweeps behind when the voice names them, from `at` seconds. */
  marks?: { text: string; at: number }[]
}

/**
 * Claude Code's ⎿, drawn: the bundled mono subset has no glyph for it, and a fallback font draws it at the wrong
 * size. One character wide, in the line's own colour.
 */
export function Elbow() {
  return (
    <span style={{ display: 'inline-block', width: '1ch', height: '1em', verticalAlign: '-0.05em', position: 'relative' }}>
      <span style={{ position: 'absolute', left: '0.2ch', top: '0.04em', width: '0.7ch', height: '0.6em', borderLeft: '0.09em solid currentColor', borderBottom: '0.09em solid currentColor', opacity: 0.85 }} />
    </span>
  )
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Body text with its tokens coloured and its marks swept. Plain monospace; nothing boxed. */
function Body({ line, sec }: { line: TermLine; sec: number }) {
  const tokens = line.tokens ?? []
  const marks = line.marks ?? []
  const all = [...tokens.map((t) => t.text), ...marks.map((m) => m.text)].filter(Boolean)
  if (!all.length) return <>{line.text}</>
  const re = new RegExp(`(${[...new Set(all)].sort((a, b) => b.length - a.length).map(escape).join('|')})`, 'g')
  return (
    <>
      {line.text.split(re).map((part, i) => {
        const tok = tokens.find((t) => t.text === part)
        const mark = marks.find((m) => m.text === part)
        const p = mark ? interpolate(sec - mark.at, [0, 0.45], [0, 1], { ...clamp, easing: ease }) : 0
        if (!tok && !mark) return <span key={i}>{part}</span>
        return (
          <span
            key={i}
            style={{
              color: tok?.color,
              fontWeight: tok?.bold ? 600 : undefined,
              backgroundImage: mark ? 'linear-gradient(rgba(237,239,241,0.16), rgba(237,239,241,0.16))' : undefined,
              backgroundRepeat: 'no-repeat',
              backgroundSize: `${p * 100}% 100%`,
              borderRadius: 3,
            }}
          >
            {part}
          </span>
        )
      })}
    </>
  )
}

/** A Claude Code session, drawn from a recorded run: each line arrives at its time; prompts and commands type. */
export function Terminal({ title, color, lines, sec, style, size = 16 }: { title: ReactNode; color: string; lines: TermLine[]; sec: number; style?: CSSProperties; size?: number }) {
  const shown = lines.filter((l) => sec >= l.at)
  return (
    <div
      style={{
        background: '#0c0f12',
        borderRadius: 14,
        boxShadow: `0 30px 80px -30px rgba(0,0,0,0.9), inset 0 0 0 1px ${C.line}`,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        ...style,
      }}
    >
      <div style={{ height: 42, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px', borderBottom: `1px solid ${C.line}`, fontFamily: SANS, fontSize: 15, color: C.muted }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: color }} />
        {title}
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
          padding: '12px 18px 16px',
          overflow: 'hidden',
          fontFamily: MONO,
          fontSize: size,
          lineHeight: 1.6,
          fontVariantLigatures: 'none',
        }}
      >
        {shown.map((l, i) => {
          const age = sec - l.at
          const grow = interpolate(age, [0, 0.28], [0, 1], { ...clamp, easing: ease })
          const typing = l.kind === 'prompt' || l.kind === 'cmd'
          const typed = typing ? Math.min(l.text.length, Math.floor(age * (l.cps ?? 42))) : l.text.length
          const caret = typing && typed < l.text.length && Math.floor(age * 3) % 2 === 0
          // Lines under a tool call hang under its name, the way Claude Code indents them.
          const indent = l.kind === 'status' || l.kind === 'body' || l.kind === 'out' ? 5 : 0
          const prefix = { prompt: '> ', cmd: '$ ', tool: '● ', say: '● ', add: '+ ', del: '- ', status: '   ', body: '', out: '' }[l.kind]
          const look: CSSProperties = {
            prompt: { color: C.text },
            cmd: { color: C.text },
            tool: { color: C.text, fontWeight: 600, marginTop: 8 },
            say: { color: C.text, marginTop: 8 },
            add: { color: '#8fe0b5', background: 'rgba(60,207,142,0.08)', padding: '0 8px' },
            del: { color: '#ff9b9b', background: 'rgba(255,93,93,0.08)', padding: '0 8px' },
            status: { color: l.color ?? C.muted },
            body: { color: '#c9ced3' },
            out: { color: C.muted },
          }[l.kind]
          return (
            <div key={i} style={{ display: 'grid', gridTemplateRows: `${grow}fr`, opacity: grow, flexShrink: 0 }}>
              <div style={{ minHeight: 0, overflow: 'hidden' }}>
                <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', paddingLeft: `${indent}ch`, textIndent: prefix && indent ? `-${prefix.length}ch` : undefined, ...look }}>
                  {l.kind === 'status' ? (
                    <>
                      <Elbow />
                      {'  '}
                    </>
                  ) : (
                    prefix && <span style={{ color: l.kind === 'prompt' ? color : l.kind === 'say' ? C.text : undefined, opacity: l.kind === 'tool' ? 0.85 : 1 }}>{prefix}</span>
                  )}
                  {l.kind === 'body' ? <Body line={l} sec={sec} /> : l.text.slice(0, typed)}
                  {caret && <span style={{ display: 'inline-block', width: size * 0.55, height: size * 1.1, background: C.text, verticalAlign: 'text-bottom', marginLeft: 2 }} />}
                </div>
              </div>
            </div>
          )
        })}
        {/* Takes the room below the lines while they fit, so a session reads from the top; gives it up as they grow. */}
        <div style={{ flex: '1 1 auto', minHeight: 0 }} />
      </div>
    </div>
  )
}
