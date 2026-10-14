import { Footer } from './sections/Footer'
import { GetStarted } from './sections/GetStarted'
import { Hero } from './sections/Hero'
import { HowItWorks } from './sections/HowItWorks'
import { Nav } from './sections/Nav'
import { Problem } from './sections/Problem'
import { Proof } from './sections/Proof'
import { TowerDemo } from './sections/TowerDemo'
import { WhyGraph } from './sections/WhyGraph'

export default function App() {
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
