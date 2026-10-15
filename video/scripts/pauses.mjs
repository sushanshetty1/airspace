// The strict pause check: node scripts/pauses.mjs [file]   (default out/airspace-demo.mp4)
//
// silencedetect at -35 dB, 0.15 s. Fails when two silences come within 0.5 s of each other (a breath or a word
// fragment left between them), or when a stretch of near-silence (silences and what lies between them, when that
// is under 0.5 s) runs over 0.4 s. The opening lead-in, the deliberate pause before the results and the end card
// are allowed, and are named in the output.

import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const file = process.argv[2] ?? path.join(ROOT, 'out/airspace-demo.mp4')
const timing = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/timing.json'), 'utf8'))
const results = timing.scenes.numbers.chunks[0].start
const lastWord = timing.scenes[timing.order.at(-1)].end

const out = spawnSync('ffmpeg', ['-hide_banner', '-i', file, '-af', 'silencedetect=noise=-35dB:d=0.15', '-f', 'null', '-'], { encoding: 'utf8' }).stderr
const sil = []
for (const m of out.matchAll(/silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)/g)) sil.push([Number(m[1]), Number(m[2])])

// Near-silent stretches: silences joined when the sound between them is under 0.5 s.
const runs = []
for (const s of sil) {
  const last = runs.at(-1)
  if (last && s[0] - last.end < 0.5) {
    last.end = s[1]
    last.parts.push(s)
  } else runs.push({ start: s[0], end: s[1], parts: [s] })
}

let bad = 0
for (const r of runs) {
  const len = r.end - r.start
  const allowed = r.start < 0.05 ? 'lead-in' : Math.abs(r.end - results) < 0.15 ? 'deliberate pause before the results' : r.start >= lastWord - 0.3 ? 'end card' : ''
  const double = r.parts.length > 1
  const long = len > 0.4
  const flag = allowed ? `allowed (${allowed})` : double || long ? 'FAIL' : 'ok'
  if (flag === 'FAIL') bad++
  if (flag !== 'ok' || process.argv.includes('--all'))
    console.log(`${r.start.toFixed(3)}-${r.end.toFixed(3)}  ${len.toFixed(3)} s  ${r.parts.length} silence${r.parts.length > 1 ? 's' : ''}  ${flag}`)
}
const lens = sil.map(([a, b]) => b - a).sort((a, b) => a - b)
console.log(`${sil.length} silences of 0.15 s or more at -35 dB; ${runs.length} stretches; ${bad} failing`)
process.exit(bad ? 1 : 0)
