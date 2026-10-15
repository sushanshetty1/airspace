// Stills for review, headless: node scripts/stills.mjs [seconds ...] | --scenes | --transitions
// Writes out/stills/<time>-<scene>.jpg. With --scenes, three stills per scene; with --transitions, the middle of
// each transition.

import fs from 'node:fs'
import path from 'node:path'
import { bundle } from '@remotion/bundler'
import { renderStill, selectComposition } from '@remotion/renderer'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const OUT = path.join(ROOT, 'out/stills')
fs.mkdirSync(OUT, { recursive: true })
const args = process.argv.slice(2)

const timing = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/timing.json'), 'utf8'))
const tl = fs.readFileSync(path.join(ROOT, 'src/timeline.ts'), 'utf8')

// Scene starts, the same arithmetic as src/timeline.ts.
const TRANSITION = Object.fromEntries([...tl.matchAll(/^\s+(\w+): \{ dur: ([\d.]+), lead: ([\d.]+) \}/gm)].map((m) => [m[1], { dur: Number(m[2]), lead: Number(m[3]) }]))
const defs = [...tl.matchAll(/\{ id: '(\w+)', into: \{ kind: '(\w+)'/g)].map((m) => ({ id: m[1], kind: m[2] }))
const starts = defs.map((d, i) => ({ ...d, start: i === 0 ? 0 : timing.scenes[d.id].start - TRANSITION[d.kind].lead }))
starts.forEach((s, i) => (s.end = i < starts.length - 1 ? starts[i + 1].start + TRANSITION[starts[i + 1].kind].dur : timing.total))

const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src/index.ts'), publicDir: path.join(ROOT, 'public') })
const browserExecutable = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const composition = await selectComposition({ serveUrl, id: 'AirspaceDemo', browserExecutable, chromeMode: 'chrome-for-testing' })

let times = []
if (args.includes('--scenes')) for (const s of starts) times.push(...[0.3, 0.62, 0.9].map((f) => s.start + (s.end - s.start) * f))
if (args.includes('--transitions')) for (const s of starts.slice(1)) times.push(s.start + TRANSITION[s.kind].dur * 0.5)
times.push(...args.filter((a) => !a.startsWith('--')).map(Number))

for (const sec of times) {
  const frame = Math.min(composition.durationInFrames - 1, Math.round(sec * 30))
  const scene = [...starts].reverse().find((s) => s.start <= sec)
  const file = path.join(OUT, `${sec.toFixed(2).padStart(6, '0')}-${scene?.id}.jpg`)
  await renderStill({ serveUrl, composition, frame, output: file, imageFormat: 'jpeg', jpegQuality: 90, browserExecutable, chromeMode: 'chrome-for-testing' })
  console.log(file)
}
