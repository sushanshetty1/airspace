import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Tower and sign-in talk to `airspace serve`, which listens on 8787. AIRSPACE_API points elsewhere.
const api = process.env.AIRSPACE_API || 'http://localhost:8787'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: api, changeOrigin: true },
      // Sign-in: the GitHub redirect, its callback and sign-out.
      '/auth': { target: api, changeOrigin: true },
    },
  },
})
