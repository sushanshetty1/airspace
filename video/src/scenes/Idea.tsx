// The idea. The site's headline, then the graph Airspace keeps, drawn from the replay's own radar data
// (server/demo/replay.json) and the blog fixture it ran on: slugify, every caller and test two hops out, the two
// agents' airspaces, the call that would break, the hold. The Cypher is the README's, as the engine runs it.

import { AbsoluteFill, Img, interpolate, staticFile } from 'remotion'
import { C, MONO, SANS, ease, easeInOut } from '../brand'
import { Clip } from '../components/Clip'
import { Cypher, Elbow, Panel, clamp, pop, ramp, useSec } from '../components/ui'
import { useSceneTime } from '../timeline'

type N = { id: string; x: number; y: number; test?: boolean; agent: 'a' | 'b' | 'both'; hop: 0 | 1 | 2 }
const A = { x: 700, y: 526, r: 300 }
const B = { x: 1180, y: 526, r: 290 }

const NODES: N[] = [
  { id: 'slugify', x: A.x, y: A.y, agent: 'a', hop: 0 },
  { id: 'Post.save', x: 585, y: 646, agent: 'a', hop: 1 },
  { id: 'Tag.save', x: 545, y: 461, agent: 'a', hop: 1 },
  { id: 'test_slugify', x: 690, y: 336, agent: 'a', hop: 1, test: true },
  { id: 'tag_create', x: 455, y: 336, agent: 'a', hop: 2 },
  { id: 'test_post_save', x: 470, y: 736, agent: 'a', hop: 2, test: true },
  { id: 'test_render_post', x: 955, y: 696, agent: 'both', hop: 2, test: true },
  { id: 'render_post', x: B.x, y: B.y, agent: 'b', hop: 0 },
  { id: 'post_list', x: 1335, y: 406, agent: 'b', hop: 1 },
  { id: 'LatestPosts.item_description', x: 1310, y: 661, agent: 'b', hop: 1 },
]
const at = (id: string) => NODES.find((n) => n.id === id)!

/** Calls (and, dashed, test coverage) as the indexer records them in the fixture. */
const EDGES: [string, string][] = [
  ['Post.save', 'slugify'],
  ['Tag.save', 'slugify'],
  ['test_slugify', 'slugify'],
  ['tag_create', 'Tag.save'],
  ['test_post_save', 'Post.save'],
  ['test_render_post', 'Post.save'],
  ['test_render_post', 'render_post'],
  ['post_list', 'render_post'],
  ['LatestPosts.item_description', 'render_post'],
]

const CONE = `// Impact cone: what depends on a task's claims, 2 hops out
MATCH (t:Task {id: $task})-[c:CLAIMS]->(s:Symbol)
WHERE c.lease_until > $now
MATCH (d:Symbol)-[:CALLS|COVERS|INHERITS*1..2]->(s)
MERGE (t)-[:CONE]->(d)`

const CLEARANCE = `// Clearance: is this new call into a contract
// another agent has changed?
MATCH (a:Agent)-[:FLYING]->(o:Task)-[:CHANGED]->
      (cc:ContractChange {qualname: $callee})
WHERE a.id <> $agent AND o.status IN $standing
RETURN cc.old_sig, cc.new_sig, a.id`

function Airspace({ cx, cy, r, color, soft, p, label }: { cx: number; cy: number; r: number; color: string; soft: string; p: number; label: string }) {
  return (
    <g opacity={Math.min(1, p * 2)}>
      <circle cx={cx} cy={cy} r={r * p} fill={soft} stroke={color} strokeOpacity={0.75} strokeWidth={2} />
      <circle cx={cx} cy={cy} r={r * 0.5 * p} fill="none" stroke={color} strokeOpacity={0.35} strokeWidth={1.2} strokeDasharray="2 7" />
      <text x={cx} y={cy - r - 18} textAnchor="middle" fill={color} fontFamily={MONO} fontSize={22} fontWeight={600} opacity={ramp(p, 0.6, 0.4)}>
        {label}
      </text>
    </g>
  )
}

export function Idea() {
  const { sec, fps } = useSec()
  const { c, word, inEnd } = useSceneTime()

  const graphAt = c(1) - 0.35
  const falkor = word('Falkor', c(1))
  const nodeP = (i: number) => pop(sec, graphAt + 0.15 + i * 0.07, fps, { damping: 15, stiffness: 160, mass: 0.7 })
  const edgeP = (i: number) => ramp(sec, graphAt + 0.5 + i * 0.08, 0.55, easeInOut)
  const shapeChip = pop(sec, word('shape', c(1)) - 0.1, fps)

  const aSpace = pop(sec, word('claims', c(2)) - 0.35, fps, { damping: 20, stiffness: 70, mass: 1 })
  const bSpace = pop(sec, word('airspace', c(2)) - 0.2, fps, { damping: 20, stiffness: 70, mass: 1 })
  const coneTint = ramp(sec, word('caller', c(2)) - 0.1, 0.6)

  // The edit agent-b is about to write, flying in to be checked.
  const editAt = c(3) - 0.1
  const fly = interpolate(sec, [editAt, editAt + 1.1], [0, 1], { ...clamp, easing: easeInOut })
  const call = ramp(sec, editAt + 1.0, 0.6, easeInOut)
  const ping = (sec - (editAt + 1.4)) % 1.1
  const held = pop(sec, word('held', c(4)) - 0.12, fps, { damping: 12, stiffness: 190, mass: 0.6 })
  const told = pop(sec, word('told', c(4)) - 0.15, fps)

  // Cypher: the cone query when the voice says FalkorDB, the clearance query when it says Cypher.
  const card = pop(sec, falkor - 0.05, fps)
  const swap = ramp(sec, c(5) - 0.15, 0.45)
  const cardBig = ramp(sec, c(5) - 0.2, 0.6)

  const lensX = (A.x + A.r + (B.x - B.r)) / 2
  const fx = interpolate(fly, [0, 1], [1330, B.x + 6])
  const fy = interpolate(fly, [0, 1], [880, B.y + 52]) - Math.sin(fly * Math.PI) * 120

  return (
    <AbsoluteFill>
      <Clip
        take="hero"
        from={0}
        to={graphAt}
        exit
        warp={[
          [0, 26.0],
          [graphAt + 0.6, 26.0 + (graphAt + 0.6) * 0.9],
        ]}
        shots={[
          { at: 0, rect: null },
          { at: inEnd, rect: { x: 200, y: 120, w: 1200, h: 560 }, stiffness: 25 },
        ]}
        cursor={false}
      />

      {sec > graphAt - 0.1 && (
        <AbsoluteFill style={{ opacity: ramp(sec, graphAt - 0.1, 0.3) }}>
          <div style={{ position: 'absolute', left: 150, top: 46, display: 'flex', alignItems: 'center', gap: 12, opacity: ramp(sec, falkor - 0.2, 0.5) }}>
            <Img src={staticFile('logos/falkordb.svg')} style={{ width: 34, height: 34, borderRadius: 7 }} />
            <span style={{ fontFamily: SANS, fontSize: 22, color: C.text, fontWeight: 600 }}>FalkorDB</span>
            <span style={{ fontFamily: SANS, fontSize: 20, color: C.muted }}>one live graph per repo</span>
          </div>
          <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
            <defs>
              <clipPath id="ideaA">
                <circle cx={A.x} cy={A.y} r={A.r * aSpace} />
              </clipPath>
            </defs>
            <Airspace cx={A.x} cy={A.y} r={A.r} color={C.a} soft={C.aSoft} p={aSpace} label="agent-a" />
            <Airspace cx={B.x} cy={B.y} r={B.r} color={C.b} soft={C.bSoft} p={bSpace} label="agent-b" />
            {/* The overlap: where the airspaces meet. It turns orange on the hold. */}
            <circle cx={B.x} cy={B.y} r={B.r * bSpace} fill={C.accent} opacity={held * 0.92} clipPath="url(#ideaA)" />

            {EDGES.map(([from, to], i) => {
              const f = at(from)
              const t = at(to)
              const p = edgeP(i)
              const test = f.test
              return (
                <line
                  key={i}
                  x1={f.x}
                  y1={f.y}
                  x2={f.x + (t.x - f.x) * p}
                  y2={f.y + (t.y - f.y) * p}
                  stroke={coneTint > 0 && f.agent !== 'b' ? C.a : C.lineStrong}
                  strokeOpacity={0.4 + 0.5 * (f.agent === 'b' ? bSpace : coneTint)}
                  strokeWidth={2}
                  strokeDasharray={test ? '4 6' : undefined}
                />
              )
            })}

            {/* agent-b's new call: render_post -> slugify, the call that would break. */}
            <line x1={B.x} y1={B.y} x2={B.x + (A.x - B.x) * call} y2={A.y} stroke={held > 0.5 ? C.accent : C.b} strokeWidth={3.5} strokeDasharray={held > 0.5 ? '10 8' : undefined} />
            {sec > editAt + 1.4 && held < 0.5 && (
              <circle cx={A.x} cy={A.y} r={20 + ping * 120} fill="none" stroke={C.text} strokeOpacity={Math.max(0, 0.6 - ping * 0.6)} strokeWidth={2} />
            )}

            {NODES.map((n, i) => {
              const p = nodeP(i)
              const color = n.agent === 'b' ? C.b : n.agent === 'both' ? C.text : C.a
              const lit = n.agent === 'b' ? bSpace : coneTint
              const center = n.hop === 0
              return (
                <g key={n.id} opacity={Math.min(1, p * 1.5)} transform={`translate(${n.x} ${n.y}) scale(${0.5 + 0.5 * p})`}>
                  {center && <circle r={17} fill={C.bg} stroke={color} strokeWidth={2.5} />}
                  {n.test ? (
                    <rect x={-6} y={-6} width={12} height={12} fill={lit > 0.3 || center ? color : C.muted} />
                  ) : (
                    <circle r={center ? 8.5 : 6.5} fill={lit > 0.3 || center ? color : C.muted} />
                  )}
                  <text
                    x={0}
                    y={center ? 44 : n.y > A.y ? 30 : -16}
                    textAnchor="middle"
                    fill={C.text}
                    fontFamily={MONO}
                    fontSize={center ? 25 : 18}
                    fontWeight={center ? 600 : 400}
                    paintOrder="stroke"
                    stroke={C.deep}
                    strokeWidth={5}
                  >
                    {n.id === 'LatestPosts.item_description' ? 'LatestPosts.item_de…' : n.id}
                  </text>
                </g>
              )
            })}
            {held > 0.02 && (
              <text x={lensX} y={A.y - 16} textAnchor="middle" fill={C.accentInk} fontFamily={SANS} fontWeight={700} fontSize={27} opacity={held} transform={`translate(${lensX} ${A.y}) scale(${0.6 + 0.4 * held}) translate(${-lensX} ${-A.y})`}>
                Hold
              </text>
            )}
          </svg>

          {/* The shape of one call, carried on its edge. */}
          <div
            style={{
              position: 'absolute',
              right: 1920 - 618,
              top: 574,
              transform: `translateY(${(1 - shapeChip) * 10}px)`,
              opacity: shapeChip * (1 - ramp(sec, c(3) - 0.3, 0.4)),
              fontFamily: MONO,
              fontSize: 16,
              color: C.text,
              background: C.surface2,
              padding: '6px 10px',
              borderRadius: 7,
              boxShadow: `inset 0 0 0 1px ${C.lineStrong}`,
              whiteSpace: 'nowrap',
            }}
          >
            slugify(self.title) <span style={{ color: C.muted, fontFamily: SANS }}>· 1 positional, result used</span>
          </div>

          {/* The edit, flying in to be checked. */}
          {fly > 0 && fly < 1 && (
            <div
              style={{
                position: 'absolute',
                left: fx - 20,
                top: fy - 20,
                fontFamily: MONO,
                fontSize: 17,
                color: '#8fe0b5',
                background: '#0c0f12',
                padding: '9px 13px',
                borderRadius: 9,
                boxShadow: `inset 0 0 0 1px ${C.lineStrong}, 0 16px 40px -10px rgba(0,0,0,0.8)`,
                whiteSpace: 'nowrap',
                transform: `scale(${1 - fly * 0.3})`,
                transformOrigin: '0 0',
                opacity: 1 - ramp(fly, 0.8, 0.2),
              }}
            >
              + slugify(post.title, allow_unicode=True)
            </div>
          )}

          {/* What agent-b is told, as its terminal prints it: plain lines under the blocked edit. */}
          <div
            style={{
              position: 'absolute',
              left: 1040,
              top: 840,
              opacity: Math.min(1, told * 1.5) * (1 - cardBig),
              transform: `translateY(${(1 - told) * 14}px)`,
              fontFamily: MONO,
              fontSize: 17,
              lineHeight: 1.6,
              color: '#c9ced3',
              whiteSpace: 'pre',
              fontVariantLigatures: 'none',
              textShadow: `0 0 12px ${C.deep}, 0 0 4px ${C.deep}`,
            }}
          >
            <div style={{ color: '#e8836a' }}>
              <Elbow />
              {'  PreToolUse:Edit hook blocked:'}
            </div>
            <div>
              {'   Airspace hold: '}
              <span style={{ color: C.text, fontWeight: 600 }}>utils.text.slugify</span>
              {' is being changed by '}
              <span style={{ color: C.a }}>agent-a</span>.
            </div>
            <div>
              {'   New signature: '}
              <span style={{ color: '#8fe0b5' }}>slugify(value, *, unicode=False)</span>
            </div>
          </div>

          <AbsoluteFill style={{ background: C.deep, opacity: cardBig * 0.7 }} />
          {/* The query. */}
          <div
            style={{
              position: 'absolute',
              left: interpolate(cardBig, [0, 1], [1262, 360]),
              top: interpolate(cardBig, [0, 1], [34, 300]),
              width: interpolate(cardBig, [0, 1], [526, 1200]),
              opacity: Math.min(1, card * 1.5),
              transform: `translateY(${(1 - card) * -20}px)`,
            }}
          >
            <Panel
              title={
                <>
                  <span style={{ fontWeight: 600 }}>Cypher</span>
                  <span style={{ color: C.muted }}>{swap > 0.5 ? 'run before every edit' : 'run on every claim'}</span>
                </>
              }
              right={swap > 0.5 ? <span style={{ fontFamily: SANS, fontSize: 15, color: C.muted }}>no model call</span> : undefined}
              style={{ boxShadow: `0 40px 100px -30px rgba(0,0,0,0.95), inset 0 0 0 1px ${C.lineStrong}` }}
            >
              <div style={{ padding: '14px 18px 16px', opacity: swap < 0.5 ? 1 - swap * 2 : swap * 2 - 1 }}>
                <Cypher code={swap < 0.5 ? CONE : CLEARANCE} size={interpolate(cardBig, [0, 1], [13.2, 24])} />
              </div>
            </Panel>
          </div>
        </AbsoluteFill>
      )}
      {void ease}
    </AbsoluteFill>
  )
}
