import { Check, Copy } from '@phosphor-icons/react'
import { useState } from 'react'
import { Brackets, ButtonLink, Container, Fig, REPO_URL } from '../ui'

const commands = ['docker compose up -d falkordb', 'uvx airspace install-hooks']

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          window.setTimeout(() => setDone(false), 1600)
        } catch {
          /* clipboard blocked: the text stays selectable */
        }
      }}
      aria-label={done ? 'Copied' : 'Copy commands'}
      className="inline-flex items-center gap-1.5 font-label text-[11px] tracking-[0.12em] text-muted transition-colors hover:text-text"
    >
      {done ? <Check size={14} weight="bold" className="text-ok" /> : <Copy size={14} weight="bold" />}
      {done ? 'COPIED' : 'COPY'}
    </button>
  )
}

const works = [
  { name: 'Claude Code', logo: '/logos/claude.svg' },
  { name: 'Any MCP client', logo: '/logos/modelcontextprotocol.svg' },
  { name: 'Python repos', logo: '/logos/python.svg' },
]

export function GetStarted() {
  return (
    <section id="start" className="border-t border-line py-24 sm:py-32">
      <Container className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-16">
        <div>
          <h2 className="display text-[34px] text-balance sm:text-[46px]">Two commands to start.</h2>
          <p className="mt-5 max-w-[46ch] text-[17px] leading-relaxed text-muted sm:text-[18px]">Hooks for Claude Code today. The same tools work from any MCP client.</p>
          <ul className="mt-9 flex flex-wrap items-center gap-x-8 gap-y-4" aria-label="Works with">
            {works.map((w) => (
              <li key={w.name} className="flex items-center gap-2.5 text-[15px] text-muted">
                <span className="logo-mask size-[22px] text-text" style={{ maskImage: `url(${w.logo})`, WebkitMaskImage: `url(${w.logo})` }} aria-hidden="true" />
                {w.name}
              </li>
            ))}
          </ul>
        </div>

        <div>
          <Fig n="07">Install</Fig>
          <Brackets className="mt-4">
            <div className="border border-line bg-surface">
              <div className="flex h-11 items-center justify-between border-b border-line px-5">
                <span className="font-mono text-[12px] text-faint">~/your-repo</span>
                <CopyButton text={commands.join('\n')} />
              </div>
              <pre className="overflow-x-auto px-5 py-6 font-mono text-[14px] leading-[2]">
                {commands.map((c) => (
                  <span key={c} className="block">
                    <span className="text-accent select-none">$ </span>
                    <span className="text-text">{c}</span>
                  </span>
                ))}
              </pre>
            </div>
          </Brackets>
          <ButtonLink href={REPO_URL} variant="secondary" className="mt-5">
            View on GitHub
          </ButtonLink>
        </div>
      </Container>
    </section>
  )
}
