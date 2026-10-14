import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'
import { Frame } from './ui'

// Lines in the shape Claude Code prints them: a tool call, then its result under ⎿.
export type TermLine =
  | { kind: 'prompt'; text: ReactNode }
  | { kind: 'tool'; text: ReactNode }
  | { kind: 'diff'; text: ReactNode }
  | { kind: 'result'; head: ReactNode; lines?: ReactNode[] }

function Line({ line }: { line: TermLine }) {
  switch (line.kind) {
    case 'prompt':
      return (
        <p className="text-muted">
          <span className="text-faint">&gt; </span>
          {line.text}
        </p>
      )
    case 'tool':
      return (
        <p className="text-text">
          <span className="text-ok">● </span>
          {line.text}
        </p>
      )
    case 'diff':
      return <p className="pl-[2ch] text-ok">{line.text}</p>
    case 'result':
      return (
        <div className="grid grid-cols-[3ch_minmax(0,1fr)] pl-[2ch]">
          <span className="text-faint">⎿</span>
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2.5 text-text">{line.head}</div>
            {line.lines?.map((l, i) => (
              <p key={i} className="text-muted">
                {l}
              </p>
            ))}
          </div>
        </div>
      )
  }
}

export function Terminal({ agent, color, lines, className = '' }: { agent: string; color: string; lines: TermLine[]; className?: string }) {
  return (
    <Frame
      className={className}
      title={
        <>
          <span className="font-mono font-semibold" style={{ color }}>
            {agent}
          </span>
          <span className="truncate font-mono text-faint">~/blog-api</span>
        </>
      }
      right={<span className="text-[12.5px] text-faint">Claude Code</span>}
    >
      <div className="space-y-3.5 overflow-x-auto px-5 py-5 font-mono text-[12.5px] leading-[1.7] sm:text-[13px]">
        <AnimatePresence initial={false}>
          {lines.map((line, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}>
              <Line line={line} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Frame>
  )
}
