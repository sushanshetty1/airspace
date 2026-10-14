import { ArrowRight, ArrowUpRight } from '@phosphor-icons/react'
import { ButtonLink, Container, REPO_URL, sectionHref, Wordmark } from '../ui'

const columns = [
  {
    title: 'Product',
    links: [
      { label: 'How it works', href: '#how' },
      { label: 'Tower', href: '#tower' },
      { label: 'Why a graph', href: '#graph' },
      { label: 'Results', href: '#proof' },
      { label: 'Playground', href: '/playground' },
    ],
  },
  {
    title: 'Project',
    links: [
      { label: 'GitHub', href: REPO_URL, external: true },
      { label: 'README', href: `${REPO_URL}#readme`, external: true },
      { label: 'Licence', href: `${REPO_URL}/blob/main/LICENSE`, external: true },
    ],
  },
  {
    title: 'Built with',
    links: [
      { label: 'FalkorDB', href: 'https://www.falkordb.com', external: true },
      { label: 'Claude Code', href: 'https://claude.com/claude-code', external: true },
      { label: 'Model Context Protocol', href: 'https://modelcontextprotocol.io', external: true },
    ],
  },
]

export function Footer() {
  return (
    <footer className="relative overflow-hidden border-t border-line">
      <Container className="py-20 sm:py-28">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
          <h2 className="display max-w-[720px] text-[40px] text-balance sm:text-[60px]">Let your agents fly together.</h2>
          <ButtonLink href={sectionHref('start')} className="self-start lg:self-auto">
            Get started <ArrowRight size={16} weight="bold" className="transition-transform group-hover:translate-x-0.5" />
          </ButtonLink>
        </div>

        <div className="mt-20 grid gap-12 border-t border-line pt-12 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <a href={sectionHref('top')}>
              <Wordmark />
            </a>
            <p className="mt-5 max-w-[300px] text-[14px] leading-relaxed text-muted">
              Built for the FalkorDB Hackathon 2026. Open source under Apache-2.0. Made with help from Claude Code, as the README explains.
            </p>
          </div>
          {columns.map((col) => (
            <div key={col.title}>
              <p className="text-[13.5px] font-semibold text-text">{col.title}</p>
              <ul className="mt-4 space-y-3">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <a href={l.href.startsWith('#') ? sectionHref(l.href.slice(1)) : l.href} className="group inline-flex items-center gap-1.5 text-[15px] text-muted transition-colors hover:text-text">
                      {l.label}
                      {'external' in l && l.external && <ArrowUpRight size={13} weight="bold" className="opacity-0 transition-opacity group-hover:opacity-100" />}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Container>

      {/* The wordmark, set large and cropped by the bottom edge of the page. */}
      <div className="pointer-events-none -mb-[5vw] select-none lg:-mb-[62px]" aria-hidden="true">
        <Container>
          <p className="display text-center text-[21vw] leading-[0.8] text-surface-2 lg:text-[252px]">Airspace</p>
        </Container>
      </div>
    </footer>
  )
}
