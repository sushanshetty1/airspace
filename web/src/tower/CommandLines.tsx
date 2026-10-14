/**
 * Shell commands that wrap on narrow screens: each command keeps a hanging indent, words
 * such as --root never split at their hyphens, and only a long key breaks mid-word.
 * Goes inside a <pre> with `whitespace-normal`.
 */
export function CommandLines({ lines }: { lines: string[] }) {
  return (
    <>
      {lines.map((line) => (
        <span key={line} className={`block [font-variant-ligatures:none] ${lines.length > 1 ? 'pl-[2ch] -indent-[2ch]' : ''}`}>
          {line.split(' ').map((word, i) => (
            <span key={i}>
              {i > 0 && ' '}
              <span className={word.length > 24 ? '[overflow-wrap:anywhere]' : 'whitespace-nowrap'}>{word}</span>
            </span>
          ))}
          {/* A real line break, so selecting the commands and copying them gives one command per line. */}
          <br />
        </span>
      ))}
    </>
  )
}
