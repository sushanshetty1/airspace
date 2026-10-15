// Airspace's own palette and type, as the site defines them (web/src/index.css): near-black radar surfaces,
// international orange only for holds and collisions, cyan and violet only for agents.
import { Easing } from 'remotion'

export const C = {
  bg: '#0a0c0e',
  deep: '#06080a',
  surface: '#101317',
  surface2: '#161a1f',
  line: '#20262c',
  lineStrong: '#2d353c',
  text: '#edeff1',
  muted: '#8f979f',
  faint: '#5c646c',
  accent: '#ff5a1f',
  accentInk: '#170700',
  accentSoft: 'rgba(255,90,31,0.13)',
  a: '#45c4e6',
  aSoft: 'rgba(69,196,230,0.08)',
  b: '#b18cff',
  bSoft: 'rgba(177,140,255,0.08)',
  c: '#9fcb6b',
  ok: '#3ccf8e',
  okSoft: 'rgba(60,207,142,0.12)',
  bad: '#ff5d5d',
  badSoft: 'rgba(255,93,93,0.1)',
}

export const SANS = "'Schibsted Grotesk', ui-sans-serif, system-ui, sans-serif"
// Menlo after JetBrains Mono for any glyph the bundled latin subset lacks.
export const MONO = "'JetBrains Mono', Menlo, ui-monospace, monospace"

export const FPS = 30
export const W = 1920
export const H = 1080

/** The slab footage sits on: the captures' own 1600x900 viewport, one CSS pixel to one video pixel. */
export const SLAB = { x: 160, y: 26, w: 1600, h: 900, r: 18 }
/** The caption band under the slab. */
export const BAND = { top: SLAB.y + SLAB.h + 8, bottom: H - 8 }

/** The site's ease, [0.22, 1, 0.36, 1]. */
export const ease = Easing.bezier(0.22, 1, 0.36, 1)
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1)
export const easeIn = Easing.bezier(0.55, 0, 1, 0.45)
