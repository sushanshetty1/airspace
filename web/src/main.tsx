import '@fontsource-variable/archivo/standard.css'
import '@fontsource/b612-mono/400.css'
import '@fontsource/b612-mono/700.css'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
