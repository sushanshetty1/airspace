#!/usr/bin/env node
// The local stack for the signed-in takes: `airspace serve` on 8810 and Vite on 4210, against the
// airspace-falkordb-1 container on 6379, with graphs of the video's own (airspace_accounts_video, the workspace's
// graph, airspace_video_local). GitHub sign-in is configured with placeholder values so the app shows it; the take
// signs in with a session cookie made by scripts in this folder instead of a GitHub round trip.
//
//   node capture/stack.mjs api     the API (foreground)
//   node capture/stack.mjs web     Vite (foreground)

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const VIDEO = path.resolve(new URL('..', import.meta.url).pathname)
const ROOT = path.resolve(VIDEO, '..')
export const DATA = path.join(VIDEO, '.stack-data')
export const API_PORT = 8810
export const WEB_PORT = 4210

export function stackEnv() {
  const secret = fs.readFileSync(path.join(DATA, 'secret'), 'utf8').trim()
  return {
    ...process.env,
    AIRSPACE_SECRET: secret,
    GITHUB_CLIENT_ID: 'video-local',
    GITHUB_CLIENT_SECRET: 'video-local',
    AIRSPACE_ACCOUNTS_GRAPH: 'airspace_accounts_video',
    AIRSPACE_GRAPH: 'airspace_video_local',
    AIRSPACE_PUBLIC_URL: `http://localhost:${WEB_PORT}`,
    AIRSPACE_PLAYGROUND_REPO: path.join(DATA, 'no-demo'),
    AIRSPACE_CONFIG_DIR: path.join(DATA, 'config'),
    AIRSPACE_CACHE_DIR: path.join(DATA, 'cache'),
  }
}

const main = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href
const what = main ? process.argv[2] : undefined
if (what === 'api') {
  const child = spawn('uv', ['run', '--project', path.join(ROOT, 'server'), 'airspace', 'serve', '--root', path.join(DATA, 'blog'), '--port', String(API_PORT)], {
    env: stackEnv(),
    stdio: 'inherit',
  })
  child.on('exit', (c) => process.exit(c ?? 1))
} else if (what === 'web') {
  const child = spawn('npx', ['vite', '--port', String(WEB_PORT), '--strictPort'], {
    cwd: path.join(ROOT, 'web'),
    env: { ...process.env, AIRSPACE_API: `http://localhost:${API_PORT}` },
    stdio: 'inherit',
  })
  child.on('exit', (c) => process.exit(c ?? 1))
} else if (what === 'run') {
  // node capture/stack.mjs run <command> [args]: a command in the stack's environment, from the repo root.
  const [cmd, ...args] = process.argv.slice(3)
  const child = spawn(cmd, args, { cwd: process.env.STACK_CWD || ROOT, env: stackEnv(), stdio: 'inherit' })
  child.on('exit', (c) => process.exit(c ?? 1))
} else if (what) {
  console.error('usage: stack.mjs api|web|run <command>')
  process.exit(2)
}
