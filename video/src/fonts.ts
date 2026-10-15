import { continueRender, delayRender, staticFile } from 'remotion'

// Schibsted Grotesk (the site's one typeface) and JetBrains Mono (only inside real code), as variable fonts,
// loaded before any frame.
const faces: [string, string][] = [
  ['Schibsted Grotesk', 'fonts/schibsted-grotesk-latin-wght-normal.woff2'],
  ['JetBrains Mono', 'fonts/jetbrains-mono-latin-wght-normal.woff2'],
]

let started = false

export function loadFonts() {
  if (started || typeof document === 'undefined') return
  started = true
  const handle = delayRender('fonts')
  Promise.all(
    faces.map(async ([family, file]) => {
      const face = new FontFace(family, `url(${staticFile(file)}) format('woff2')`, { weight: '100 900', style: 'normal' })
      await face.load()
      ;(document.fonts as unknown as { add: (f: FontFace) => void }).add(face)
    }),
  )
    .catch((e) => console.error(e))
    .finally(() => continueRender(handle))
}
