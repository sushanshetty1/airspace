import type { ComponentType } from 'react'
import { AbsoluteFill, Html5Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig } from 'remotion'
import { Captions } from './components/Captions'
import { Transitioned } from './components/Transitions'
import { Backdrop } from './components/ui'
import { loadFonts } from './fonts'
import { Close } from './scenes/Close'
import { Idea } from './scenes/Idea'
import { Numbers } from './scenes/Numbers'
import { Open } from './scenes/Open'
import { TowerScene } from './scenes/Tower'
import { Memory, Playground, Preflight, Workspaces } from './scenes/Walkthrough'
import { SceneContext, placed, sceneTime, toFrames } from './timeline'

loadFonts()

const SCENES: Record<string, ComponentType> = {
  open: Open,
  idea: Idea,
  tower: TowerScene,
  preflight: Preflight,
  memory: Memory,
  playground: Playground,
  workspaces: Workspaces,
  numbers: Numbers,
  close: Close,
}

function Ground() {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return <Backdrop t={frame / fps} />
}

export function Main() {
  const { scenes } = placed()
  return (
    <AbsoluteFill>
      <Ground />
      {scenes.map((p) => {
        const Scene = SCENES[p.id]
        return (
          <Sequence key={p.id} name={p.id} from={toFrames(p.start)} durationInFrames={toFrames(p.dur)}>
            <SceneContext.Provider value={sceneTime(p)}>
              <Transitioned scene={p}>
                <Scene />
              </Transitioned>
            </SceneContext.Provider>
          </Sequence>
        )
      })}
      <Html5Audio src={staticFile('voice/narration.wav')} />
      <Captions />
    </AbsoluteFill>
  )
}
