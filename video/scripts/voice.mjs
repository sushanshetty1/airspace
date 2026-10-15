// The voiceover: one continuous narration track, and the timing the composition is cut to.
//
//   npm run voice            ElevenLabs when ELEVENLABS_API_KEY is set (env or ~/.zshrc), else macOS `say` drafts
//   npm run voice -- --draft macOS `say` drafts, whatever keys exist
//
// Each scene is one text-to-speech request "with timestamps" (its neighbours' text goes along as context, so the
// delivery flows across scenes). Responses are cached under voice/cache by a hash of the voice, the settings and the
// scene's text, so only scenes whose text changed are generated again, and paid for.
//
// Assembly makes the narration continuous: every chunk (a caption-sized line) is cut out of its scene's audio where
// its sound starts and stops, with a short pad and fades; every pause of GATE_MIN or more is gated to one clean
// silence and a pause inside a line is shortened to MAX_INNER; and each line starts `gap` seconds (0.15 to 0.35; one
// longer pause is allowed, set on a scene) after the previous line's last sound. The assembled track is then held to
// the pause rule (no pause over MAX_PAUSE, no two pauses within 0.5 s; scripts/pauses.mjs checks the same rule on
// the render). The track is loudness-matched to -16 LUFS once, as a whole, and an even room tone
// at about -66 dBFS runs under all of it so no join drops to digital silence. Written to public/voice/narration.wav;
// timing to src/timing.json.

import { execFileSync, spawnSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { readKey } from './keys.mjs'

const ROOT = path.resolve(new URL('..', import.meta.url).pathname)
const script = JSON.parse(fs.readFileSync(path.join(ROOT, 'narration/script.json'), 'utf8'))
const CACHE = path.join(ROOT, 'voice/cache')
const OUT = path.join(ROOT, 'public/voice')
const RATE = 48000
const PACE = script.pace ?? {}
const GAP = PACE.gap ?? 0.24
const START = PACE.start ?? 0.6
const TAIL = PACE.tail ?? 2.5
const PRE = 0.06 // pad kept before a line's first character
const POST = 0.16 // and after its last, for the decay
const FADE = 0.012
const MAX_INNER = 0.3 // a pause inside a line is shortened to this
const GATE_MIN = 0.25 // a pause this long or longer is gated to one clean silence
const MAX_PAUSE = 0.36 // no pause between or inside lines runs longer, at silencedetect's -35 dB
const DELIBERATE = [] // output times of the deliberate pauses (a scene's own `gap` over 0.5 s)
const LINE_GAPS = [] // output times of the pauses between lines, [end of one, start of the next]
// Sound means louder than SILENT_DB once the track is loudness-matched (silencedetect checks -40 dBFS), held for
// 90 ms, so a lone click is not sound.
const SILENT_DB = -33
let LOUD = 0.01
fs.mkdirSync(CACHE, { recursive: true })
fs.mkdirSync(OUT, { recursive: true })

const draft = process.argv.includes('--draft')
const key = draft ? '' : readKey('ELEVENLABS_API_KEY')
const provider = key ? 'elevenlabs' : 'say'
console.log(`voice: ${provider === 'elevenlabs' ? `ElevenLabs ${script.voice.model_id}, ${script.voice.voice_name}` : `macOS say (${script.voice.draft_voice}), draft`}`)

const speakOf = (c) => c.speak ?? c.text
const sceneText = (s) => s.chunks.map(speakOf).join(' ')

function hashOf(scene) {
  const v = script.voice
  const basis = provider === 'elevenlabs' ? [v.voice_id, v.model_id, v.output_format, JSON.stringify(v.settings)] : ['say', v.draft_voice]
  return crypto.createHash('sha1').update([...basis, sceneText(scene)].join('\n')).digest('hex').slice(0, 12)
}

async function eleven(scene, i) {
  const v = script.voice
  const prev = script.scenes[i - 1]
  const next = script.scenes[i + 1]
  const body = {
    text: sceneText(scene),
    model_id: v.model_id,
    voice_settings: v.settings,
    ...(prev ? { previous_text: sceneText(prev) } : {}),
    ...(next ? { next_text: sceneText(next) } : {}),
  }
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${v.voice_id}/with-timestamps?output_format=${v.output_format}`, {
      method: 'POST',
      headers: { 'xi-api-key': key, 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (res.ok) {
      const out = await res.json()
      return { audio: Buffer.from(out.audio_base64, 'base64'), ext: 'mp3', alignment: out.alignment }
    }
    const text = await res.text()
    if (attempt < 3 && (res.status === 429 || res.status >= 500)) {
      await new Promise((r) => setTimeout(r, 4000 * attempt))
      continue
    }
    throw new Error(`ElevenLabs ${res.status}: ${text.slice(0, 300)}`)
  }
}

/** macOS `say`, one file per chunk, joined; characters are spread evenly over each chunk's speech. Plays nothing. */
function say(scene) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'airspace-say-'))
  const characters = []
  const starts = []
  const ends = []
  const parts = []
  let t = 0
  scene.chunks.forEach((c, i) => {
    const text = speakOf(c) + (i < scene.chunks.length - 1 ? ' ' : '')
    const aiff = path.join(tmp, `${i}.aiff`)
    execFileSync('say', ['-v', script.voice.draft_voice, '-r', '172', '-o', aiff, speakOf(c)])
    const wav = path.join(tmp, `${i}.wav`)
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', aiff, '-ar', String(RATE), '-ac', '1', wav])
    const d = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', wav]).toString())
    const span = Math.max(0.1, d - 0.15)
    ;[...text].forEach((ch, k) => {
      characters.push(ch)
      starts.push(t + 0.05 + (span * k) / text.length)
      ends.push(t + 0.05 + (span * (k + 1)) / text.length)
    })
    parts.push(wav)
    t += d
  })
  const list = path.join(tmp, 'list.txt')
  fs.writeFileSync(list, parts.map((p) => `file '${p}'`).join('\n'))
  const joined = path.join(tmp, 'joined.wav')
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', joined])
  const audio = fs.readFileSync(joined)
  fs.rmSync(tmp, { recursive: true, force: true })
  return { audio, ext: 'wav', alignment: { characters, character_start_times_seconds: starts, character_end_times_seconds: ends } }
}

function decode(file) {
  const raw = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(RATE), '-'], { maxBuffer: 1 << 30 })
  return new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength))
}

function wav16(samples) {
  const buf = Buffer.alloc(44 + samples.length * 2)
  buf.write('RIFF', 0)
  buf.writeUInt32LE(36 + samples.length * 2, 4)
  buf.write('WAVEfmt ', 8)
  buf.writeUInt32LE(16, 16)
  buf.writeUInt16LE(1, 20)
  buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(RATE, 24)
  buf.writeUInt32LE(RATE * 2, 28)
  buf.writeUInt16LE(2, 32)
  buf.writeUInt16LE(16, 34)
  buf.write('data', 36)
  buf.writeUInt32LE(samples.length * 2, 40)
  for (let i = 0; i < samples.length; i++) buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), 44 + i * 2)
  return buf
}

/** Two-pass EBU R128 to -16 LUFS, linear, over the whole track. */
function loudnorm(file) {
  const pass = spawnSync('ffmpeg', ['-hide_banner', '-i', file, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
  const err = pass.stderr.toString()
  const stats = JSON.parse(err.slice(err.lastIndexOf('{'), err.lastIndexOf('}') + 1))
  const tmp = file.replace(/\.wav$/, '.norm.wav')
  const af = `loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=${stats.input_i}:measured_TP=${stats.input_tp}:measured_LRA=${stats.input_lra}:measured_thresh=${stats.input_thresh}:offset=${stats.target_offset}:linear=true`
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', file, '-af', af, '-ar', String(RATE), '-ac', '1', '-c:a', 'pcm_s16le', tmp])
  fs.renameSync(tmp, file)
}

/**
 * The quiet spans of a file, in seconds: under LOUD for at least GATE_MIN, with a click or a breath shorter than
 * 90 ms inside one not breaking it. Everything in them is gated to silence (the room tone covers it), so each pause
 * is one clean silence, never two with a fragment between.
 */
function quietSpans(pcm) {
  const hop = Math.round(0.01 * RATE)
  const win = Math.round(0.03 * RATE)
  const quiet = []
  for (let i = 0; i + win <= pcm.length; i += hop) {
    let sum = 0
    for (let k = 0; k < win; k++) sum += pcm[i + k] * pcm[i + k]
    quiet.push(Math.sqrt(sum / win) < LOUD)
  }
  const spans = []
  let from = null
  for (let j = 0; j <= quiet.length; j++) {
    const q = j < quiet.length && quiet[j]
    if (q && from === null) from = j
    const sustained = j >= quiet.length || quiet.slice(j, j + 9).every((x) => !x)
    if (!q && from !== null && sustained) {
      // The quiet run ends where the last window of it ends, less the window's reach into the sound.
      const a = (from * hop) / RATE
      const b = (j * hop) / RATE
      if (b - a >= GATE_MIN) spans.push([a, b])
      from = null
    }
  }
  return spans
}

/** The file with its quiet spans gated to silence, with short ramps inside each span's edges. */
function gated(pcm, spans) {
  const out = Float32Array.from(pcm)
  const r = Math.round(0.015 * RATE)
  for (const [a, b] of spans) {
    const i0 = Math.round(a * RATE)
    const i1 = Math.min(out.length, Math.round(b * RATE))
    for (let i = i0; i < i1; i++) {
      const g = Math.min(1, Math.max(0, Math.min(i - i0, i1 - i) / r))
      out[i] *= 1 - g
    }
  }
  return out
}

const out = []
const timing = {
  provider,
  voice: provider === 'elevenlabs' ? `${script.voice.voice_name} (${script.voice.model_id})` : `say ${script.voice.draft_voice}`,
  rate: RATE,
  file: 'voice/narration.wav',
  scenes: {},
}
let generated = 0
let lastEnd = null // output time of the previous line's last sound

/** Adds samples to the output at a time, growing it as needed. */
const place = (samples, at) => {
  const i0 = Math.round(at * RATE)
  while (out.length < i0 + samples.length) out.push(0)
  for (let k = 0; k < samples.length; k++) out[i0 + k] += samples[k]
}

const faded = (seg) => {
  const f = Math.round(FADE * RATE)
  const s = Float32Array.from(seg)
  for (let k = 0; k < f && k < s.length; k++) {
    s[k] *= k / f
    s[s.length - 1 - k] *= k / f
  }
  return s
}

for (const [i, scene] of script.scenes.entries()) {
  const h = hashOf(scene)
  const base = path.join(CACHE, `${scene.id}.${provider}.${h}`)
  let src
  let alignment
  const cachedExt = ['mp3', 'wav'].find((e) => fs.existsSync(`${base}.${e}`))
  if (cachedExt && fs.existsSync(`${base}.json`)) {
    src = `${base}.${cachedExt}`
    alignment = JSON.parse(fs.readFileSync(`${base}.json`, 'utf8'))
    console.log(`  ${scene.id}: cached`)
  } else {
    const got = provider === 'elevenlabs' ? await eleven(scene, i) : say(scene)
    src = `${base}.${got.ext}`
    fs.writeFileSync(src, got.audio)
    fs.writeFileSync(`${base}.json`, JSON.stringify(got.alignment))
    alignment = got.alignment
    for (const f of fs.readdirSync(CACHE)) if (f.startsWith(`${scene.id}.${provider}.`) && !f.startsWith(`${scene.id}.${provider}.${h}`)) fs.rmSync(path.join(CACHE, f))
    generated += sceneText(scene).length
    console.log(`  ${scene.id}: generated (${sceneText(scene).length} characters)`)
  }

  const chars = alignment.characters
  const st = alignment.character_start_times_seconds
  const en = alignment.character_end_times_seconds
  const spoken = chars.join('')
  const ranges = []
  let at = 0
  for (const c of scene.chunks) {
    const s = speakOf(c)
    const idx = spoken.indexOf(s, at)
    const from = idx >= 0 ? idx : at
    ranges.push([from, from + s.length])
    at = from + s.length
  }
  const firstTime = (a, b) => {
    for (let k = a; k < b; k++) if (chars[k] && chars[k].trim()) return st[k]
    return st[a] ?? 0
  }
  const lastTime = (a, b) => {
    for (let k = b - 1; k >= a; k--) if (chars[k] && chars[k].trim()) return en[k]
    return en[b - 1] ?? 0
  }

  const pcm = decode(src)
  const total = pcm.length / RATE
  const chunks = []
  const words = []
  // The threshold of sound, in this file's level: SILENT_DB after the track is matched to -16 LUFS.
  {
    const pass = spawnSync('ffmpeg', ['-hide_banner', '-i', src, '-af', 'loudnorm=I=-16:print_format=json', '-f', 'null', '-'])
    const err = pass.stderr.toString()
    const gain = -16 - Number(JSON.parse(err.slice(err.lastIndexOf('{'), err.lastIndexOf('}') + 1)).input_i)
    LOUD = Math.pow(10, (SILENT_DB - gain) / 20)
  }
  const spans = quietSpans(pcm)
  const clean = gated(pcm, spans)
  // Where sound really starts and stops near a line's alignment: the alignment's last character often runs on past
  // the voice, so the gap is measured on the audio itself.
  const rms = (t) => {
    const i = Math.round(t * RATE)
    const win = Math.round(0.03 * RATE)
    let sum = 0
    for (let k = 0; k < win && i + k < pcm.length; k++) sum += pcm[i + k] * pcm[i + k]
    return Math.sqrt(sum / win)
  }
  // Sound is 90 ms of it: a click of a few milliseconds is not.
  const loud = (t) => rms(t) > LOUD && rms(t + 0.03) > LOUD && rms(t + 0.06) > LOUD
  /** The onset of the sound around the aligned start s: back through sound already under way, or on to the next. */
  const soundStart = (s, to) => {
    let t = Math.max(0, s)
    if (loud(t)) {
      while (t > s - 0.3 && t > 0.005 && loud(t - 0.005)) t -= 0.005
      return t
    }
    for (; t < to; t += 0.005) if (loud(t)) return t
    return to
  }
  /** The last sound before `to`, scanning back no further than `from`. */
  const soundEnd = (from, to) => {
    for (let t = Math.min(total - 0.1, to - 0.09); t > from; t -= 0.005) if (loud(t)) return t + 0.09
    return from
  }
  const aligned = ranges.map(([a, b]) => [firstTime(a, b), lastTime(a, b)])
  // ElevenLabs stretches a line's last character to the next line's first, so the pause between two lines is found
  // by scanning back from where the next line's sound starts to the end of this line's last word.
  const starts = aligned.map(([s, e]) => soundStart(s, e))
  const lastWord = ranges.map(([a, b]) => {
    let k = b - 1
    while (k > a && !(chars[k] && chars[k].trim())) k--
    while (k > a && chars[k - 1] && chars[k - 1].trim()) k--
    return st[k]
  })
  const bounds = aligned.map((_, k) => [starts[k], soundEnd(Math.max(starts[k], lastWord[k] - 0.8), k < aligned.length - 1 ? starts[k + 1] - 0.03 : total)])
  if (process.env.VOICE_DEBUG === scene.id)
    console.log(scene.id, 'sound above dBFS', (20 * Math.log10(LOUD)).toFixed(1), JSON.stringify(aligned.map((x, k) => [x.map((v) => +v.toFixed(2)), bounds[k].map((v) => +v.toFixed(2))])))
  scene.chunks.forEach((c, k) => {
    const [a, b] = ranges[k]
    const [s, e] = bounds[k]
    const prevEnd = k > 0 ? bounds[k - 1][1] : 0
    const nextStart = k < scene.chunks.length - 1 ? bounds[k + 1][0] : total
    const segA = Math.max(k > 0 ? (prevEnd + s) / 2 : 0, s - PRE)
    const segB = Math.min(k < scene.chunks.length - 1 ? (e + nextStart) / 2 : total, e + POST)

    // Pauses inside the line, shortened: a map from source time to line time.
    const inner = spans.filter(([p, q]) => p > s + 0.02 && q < e - 0.02 && q - p > MAX_INNER)
    const cuts = inner.map(([p, q]) => {
      const keep = MAX_INNER
      const mid = (p + q) / 2
      return { from: mid - (q - p - keep) / 2, to: mid + (q - p - keep) / 2 }
    })
    const pieces = []
    let cur = segA
    for (const cut of cuts) {
      pieces.push([cur, cut.from])
      cur = cut.to
    }
    pieces.push([cur, segB])
    const removedBefore = (t) => cuts.reduce((n, cut) => n + (t >= cut.to ? cut.to - cut.from : t > cut.from ? t - cut.from : 0), 0)
    const map = (t) => t - removedBefore(t)

    const gap = k === 0 ? (scene.gap ?? GAP) : (c.gap ?? GAP)
    const T = lastEnd === null ? START : lastEnd + gap // output time of the line's first sound
    if (gap > 0.5 && lastEnd !== null) DELIBERATE.push(T)
    if (lastEnd !== null) LINE_GAPS.push([lastEnd, T])
    const shift = T - map(s)
    let o = map(segA) + shift
    for (const [p, q] of pieces) {
      const seg = faded(clean.subarray(Math.round(p * RATE), Math.round(q * RATE)))
      place(seg, o)
      o += seg.length / RATE
    }
    const end = map(e) + shift
    lastEnd = end
    chunks.push({ text: c.text, start: +T.toFixed(3), end: +end.toFixed(3) })
    const re = /\S+/g
    const text = spoken.slice(a, b)
    let m
    while ((m = re.exec(text))) {
      const ws = a + m.index
      const we = ws + m[0].length
      words.push({ w: m[0].replace(/[^\w'-]/g, ''), start: +(map(firstTime(ws, we)) + shift).toFixed(3), end: +(map(lastTime(ws, we)) + shift).toFixed(3) })
    }
  })
  timing.scenes[scene.id] = { start: chunks[0].start, end: chunks.at(-1).end, chunks, words }
}

// The pause rule, enforced on the assembled track at the level the finished track will have: silencedetect at
// -35 dB, 0.15 s. No pause runs over MAX_PAUSE, and no two pauses come within 0.5 s of each other (the shorter one
// of such a pair is cut to under 0.15 s). The lead-in, the deliberate pause before the results and the end are left
// alone. Cuts fall in the middle of a silence, and every time in the timing moves with them.
{
  const tmp = path.join(OUT, 'assembled.wav')
  fs.writeFileSync(tmp, wav16(Float32Array.from(out)))
  const pass = spawnSync('ffmpeg', ['-hide_banner', '-i', tmp, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
  const err = pass.stderr.toString()
  const gain = -16 - Number(JSON.parse(err.slice(err.lastIndexOf('{'), err.lastIndexOf('}') + 1)).input_i)
  fs.rmSync(tmp)
  const thr = Math.pow(10, (-36.5 - gain) / 20)
  const allowed = (a, b) => a < 0.05 || b > remap(lastEnd) - 0.01 || DELIBERATE.some((t) => a <= remap(t) && b >= remap(t) - 0.02)
  const silences = () => {
    const w = Math.round(0.005 * RATE)
    const runs = []
    let from = null
    for (let i = 0; i + w <= out.length; i += w) {
      let peak = 0
      for (let k = 0; k < w; k++) peak = Math.max(peak, Math.abs(out[i + k]))
      if (peak < thr && from === null) from = i
      if (peak >= thr && from !== null) {
        if ((i - from) / RATE >= 0.15) runs.push([from / RATE, i / RATE])
        from = null
      }
    }
    return runs.filter(([a, b]) => !allowed(a, b))
  }
  const cuts = []
  // Times after a cut move back by it. Cuts were made one at a time, each in the times of the track it cut.
  const remap = (t) => cuts.reduce((v, c) => (v >= c.to ? v - (c.to - c.from) : v > c.from ? c.from : v), t)
  const cut = (a, b, keep) => {
    // Remove the middle of [a, b] so `keep` seconds remain.
    const mid = (a + b) / 2
    const from = mid - (b - a - keep) / 2
    const to = mid + (b - a - keep) / 2
    out.splice(Math.round(from * RATE), Math.round((to - from) * RATE))
    cuts.push({ from, to })
  }
  for (let round = 0; round < 50; round++) {
    const runs = silences()
    const long = runs.find(([a, b]) => b - a > MAX_PAUSE)
    if (long) {
      cut(long[0], long[1], MAX_PAUSE - 0.02)
      continue
    }
    const pair = runs.findIndex((r, i) => i + 1 < runs.length && runs[i + 1][0] - r[1] < 0.6)
    if (pair < 0) break
    const [x, y] = [runs[pair], runs[pair + 1]]
    // A pause between lines keeps its length (0.15 to 0.35 s); the pause inside a line gives way.
    const isGap = ([a, b]) => LINE_GAPS.some(([e, s]) => a <= remap(e) + 0.1 && b >= remap(s) - 0.1)
    const shorter = isGap(x) && !isGap(y) ? y : isGap(y) && !isGap(x) ? x : x[1] - x[0] <= y[1] - y[0] ? x : y
    cut(shorter[0], shorter[1], 0.12)
  }
  // Times after a cut move back by it. Cuts were made one at a time, each in the times of the track it cut.
  for (const s of Object.values(timing.scenes)) {
    for (const c of s.chunks) {
      c.start = +remap(c.start).toFixed(3)
      c.end = +remap(c.end).toFixed(3)
    }
    for (const w of s.words) {
      w.start = +remap(w.start).toFixed(3)
      w.end = +remap(w.end).toFixed(3)
    }
    s.start = s.chunks[0].start
    s.end = s.chunks.at(-1).end
  }
  lastEnd = remap(lastEnd)
  console.log(`pause rule: ${cuts.length} cut${cuts.length === 1 ? '' : 's'} (${cuts.map((c) => (c.to - c.from).toFixed(2)).join(' ')} s)`)
}

// The tail, then loudness, then the room tone under everything.
place(new Float32Array(Math.round(TAIL * RATE)), lastEnd)
const file = path.join(OUT, 'narration.wav')
fs.writeFileSync(file, wav16(Float32Array.from(out)))
loudnorm(file)
const norm = decode(file)
let b0 = 0
let b1 = 0
let b2 = 0
let seed = 12345
const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648)
for (let i = 0; i < norm.length; i++) {
  // Pink-ish noise (Paul Kellet's economy filter), about -66 dBFS RMS, the same on every run.
  const w = random() * 2 - 1
  b0 = 0.99765 * b0 + w * 0.099046
  b1 = 0.963 * b1 + w * 0.2965164
  b2 = 0.57 * b2 + w * 1.0526913
  norm[i] += (b0 + b1 + b2 + w * 0.1848) * 0.00028
}
fs.writeFileSync(file, wav16(norm))

timing.order = script.scenes.map((s) => s.id)
timing.total = +(norm.length / RATE).toFixed(3)
fs.writeFileSync(path.join(ROOT, 'src/timing.json'), JSON.stringify(timing, null, 1) + '\n')
const gaps = []
let prev = null
for (const id of timing.order)
  for (const c of timing.scenes[id].chunks) {
    if (prev) gaps.push(+(c.start - prev.end).toFixed(2))
    prev = c
  }
console.log(`narration: ${timing.total}s, speech ends at ${lastEnd.toFixed(2)}s; gaps between lines: ${gaps.join(' ')}`)
console.log(`characters generated this run: ${generated}; script total: ${script.scenes.reduce((n, s) => n + sceneText(s).length, 0)}`)
