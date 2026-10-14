import { lazy, Suspense, useEffect, useState } from 'react'
import { Footer } from './sections/Footer'
import { GetStarted } from './sections/GetStarted'
import { Hero } from './sections/Hero'
import { HowItWorks } from './sections/HowItWorks'
import { Nav } from './sections/Nav'
import { Problem } from './sections/Problem'
import { Proof } from './sections/Proof'
import { TowerDemo } from './sections/TowerDemo'
import { WhyGraph } from './sections/WhyGraph'
import { collisionIdFrom } from './tower/nav'

const Tower = lazy(() => import('./tower/Tower'))
const Playground = lazy(() => import('./playground/Playground'))

/** The path, kept in sync with pushState navigation and the back button. */
function usePathname() {
  const [path, setPath] = useState(() => window.location.pathname)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  return path
}

function Marketing() {
  return (
    <>
      <a href="#how" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-full focus:bg-surface focus:px-4 focus:py-2">
        Skip to content
      </a>
      <Nav />
      <main>
        <Hero />
        <Problem />
        <HowItWorks />
        <TowerDemo />
        <WhyGraph />
        <Proof />
        <GetStarted />
      </main>
      <Footer />
    </>
  )
}

export default function App() {
  const path = usePathname()
  if (path === '/tower' || path.startsWith('/tower/')) {
    return (
      <Suspense fallback={<div className="min-h-dvh bg-bg" />}>
        <Tower collisionId={collisionIdFrom(path)} />
      </Suspense>
    )
  }
  if (path === '/playground' || path === '/playground/') {
    return (
      <Suspense fallback={<div className="min-h-dvh bg-bg" />}>
        <Playground />
      </Suspense>
    )
  }
  return <Marketing />
}
