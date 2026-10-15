// Every take the video uses, scripted. Run: node capture/run.mjs <take> [<take> ...]   (or `all`)
//
// Public takes record https://airspace.sushans.dev and change nothing there (the Tower replay's controls are off,
// pre-flight and the playground only read). Signed-in takes (`workspace`, `wstower`) record the local stack
// (capture/stack.mjs): the API on :8810, Vite on :4210, and the session driver capture/session.py, which sends the
// benchmark's reference edits through the real hooks into the workspace the `workspace` take creates.

import { execFile, spawnSync } from 'node:child_process'
import { promisify } from 'node:util'
import fs from 'node:fs'
import path from 'node:path'
import { LOCAL, PROD, Take, localSignIn, open } from './lib.mjs'
import { DATA, stackEnv } from './stack.mjs'

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname)
const settle = (page, ms = 600) => page.waitForTimeout(ms)

/** A step of the local session, through the real hooks (capture/session.py). */
async function session(...steps) {
  const run = promisify(execFile)
  const { stdout } = await run('uv', ['run', '--project', path.join(ROOT, 'server'), 'python', path.join(ROOT, 'video/capture/session.py'), path.join(DATA, 'blog'), ...steps], {
    env: stackEnv(),
  })
  return stdout
}

/** A command in the stack's environment; its output is kept for the composition's terminals. */
function command(name, cmd, args) {
  const r = spawnSync(cmd, args, { env: stackEnv(), encoding: 'utf8', cwd: ROOT })
  const out = { cmd: [cmd, ...args].join(' '), status: r.status, stdout: r.stdout, stderr: r.stderr }
  const file = path.join(DATA, 'commands.json')
  const all = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {}
  all[name] = out
  fs.writeFileSync(file, JSON.stringify(all, null, 1))
  if (r.status !== 0) throw new Error(`${name}: ${r.stderr}`)
  return out
}

async function scrollTo(t, page, locator, offset = 80, ms = 1600) {
  const y = await locator.evaluate((el, o) => el.getBoundingClientRect().top - o, offset)
  await t.scroll(y, ms, { x: 800, y: 450 })
}

/** Scroll the page to an absolute y, smoothly. */
async function scrollAbs(t, page, y, ms = 1400) {
  const now = await page.evaluate(() => scrollY)
  await t.scroll(y - now, ms, { el: 'html' })
}

export const TAKES = {
  /** The home page: the headline and the hero Tower card playing its loop. */
  async hero() {
    const s = await open()
    const { page } = s
    await page.goto('about:blank')
    await page.evaluate(() => (document.body.style.background = '#0a0c0e'))
    const t = new Take(s, 'hero')
    await t.start()
    t.log('hide-cursor')
    await page.goto(PROD + '/', { waitUntil: 'load' })
    t.log('loaded')
    await t.wait(1500)
    await t.mark('headline', page.locator('h1'))
    await t.wait(2500)
    // The hero card: Tower with the radar's loop.
    await t.scroll(560, 1800, { x: 800, y: 450 })
    t.log('card')
    await t.wait(12000)
    await t.stop()
    await s.browser.close()
  },

  /** Tower: the replay of a real run. Pause on the hold, open the collision, play on to the clearance. */
  async tower() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/tower', { waitUntil: 'networkidle' })
    const toggle = page.getByRole('button', { name: /the replay/ })
    await toggle.waitFor({ timeout: 30000 })
    await toggle.click() // pause
    const scrub = page.getByRole('slider', { name: 'Replay position' })
    await scrub.focus()
    await page.keyboard.press('Home')
    await page.evaluate(() => document.activeElement?.blur?.())
    await settle(page, 1200)

    const t = new Take(s, 'tower')
    await t.start()
    await t.mark('sidebar', page.locator('aside').first())
    await t.mark('radar', page.locator('section[aria-label="Radar"] svg').first())
    await t.wait(900)
    await t.click(page.getByRole('button', { name: 'Play the replay' }), { label: 'play' })
    t.log('play')
    // Frame 1 (the hold) comes 2.4 s later; pause on it.
    await page.getByText('was held editing').first().waitFor({ timeout: 10000 })
    t.log('held')
    await t.wait(500)
    await t.click(page.getByRole('button', { name: 'Pause the replay' }), { label: 'pause' })
    await t.mark('radar-held', page.locator('section[aria-label="Radar"] svg').first())
    await t.mark('activity', page.locator('aside').first())
    await t.wait(2600)
    const row = page.getByRole('button', { name: /was held at/ })
    await t.mark('row', row)
    await t.click(row, { at: 0.3, label: 'collision' })
    t.log('panel-open')
    await t.wait(1400)
    const panel = page.locator('section[aria-label="Collision"]')
    await t.mark('panel', panel)
    await t.mark('why', panel.getByText('Why it was held').locator('xpath=..'))
    await t.mark('sigs', panel.locator('dl'))
    await t.mark('radar-panel', page.locator('section[aria-label="Radar"] svg').first())
    await t.wait(5200)
    await t.click(page.getByRole('button', { name: 'Play the replay' }), { label: 'play2' })
    t.log('play2')
    await page.getByText('cleared the collision').first().waitFor({ timeout: 15000 })
    t.log('cleared')
    await t.mark('radar-cleared', page.locator('section[aria-label="Radar"] svg').first())
    await page.getByText('landed').nth(1).waitFor({ timeout: 15000 }).catch(() => {})
    t.log('landed')
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** Pre-flight on Flask: the plan as the page opens, then where the tasks meet. */
  async preflight() {
    const s = await open()
    const { page } = s
    await page.goto('about:blank')
    await page.evaluate(() => (document.body.style.background = '#0a0c0e'))
    const t = new Take(s, 'preflight')
    await t.start()
    t.log('hide-cursor')
    await page.goto(PROD + '/preflight', { waitUntil: 'load' })
    t.log('loaded')
    const result = page.locator('section[aria-label="Pre-flight result"]')
    await result.waitFor({ timeout: 30000 })
    t.log('result')
    await t.wait(1800)
    await scrollTo(t, page, page.getByText('Repo', { exact: true }).first(), 24, 1600)
    t.log('scrolled')
    await t.wait(400)
    await t.mark('tasks', page.locator('form').first())
    await t.mark('result', result)
    await t.mark('summary', result.locator('p').first())
    await t.mark('groups', result.getByText(/Must coordinate/).first().locator('xpath=../..'))
    await t.mark('meet', result.getByText('Where tasks meet').locator('xpath=..'))
    await t.wait(9000)
    await t.stop()
    await s.browser.close()
  },

  /** The playground: the story's call is held with the path; the call with the new keyword is cleared. */
  async playground() {
    const s = await open()
    const { page } = s
    await page.goto(PROD + '/playground', { waitUntil: 'networkidle' })
    await settle(page, 800)
    await page.evaluate(() => window.scrollTo(0, 230))
    await settle(page, 600)
    const t = new Take(s, 'playground')
    await t.start()
    await t.mark('fields', page.getByText('changes a signature').locator('xpath=ancestor::div[contains(@class,"grid")][1]'))
    await t.wait(800)
    await t.click(page.getByRole('button', { name: 'Check', exact: true }), { label: 'check' })
    await page.getByText('What agent-b reads in its deny reason').waitFor({ timeout: 20000 })
    t.log('verdict1')
    await t.wait(900)
    await scrollAbs(t, page, 560, 1300)
    await t.wait(500)
    await t.mark('verdict', page.getByText('Clearance', { exact: true }).locator('xpath=../..'))
    await t.wait(3400)
    await scrollAbs(t, page, 230, 1100)
    await t.wait(300)
    const call = page.getByLabel('Call')
    await t.click(call, { at: 0.5, label: 'call' })
    await page.keyboard.press('Meta+A')
    await t.type('slugify(post.title, unicode=True)', { min: 35, max: 85 })
    await t.wait(400)
    await t.click(page.getByRole('button', { name: 'Check', exact: true }), { label: 'check2' })
    await page.getByText('Cleared', { exact: true }).first().waitFor({ timeout: 20000 }).catch(() => console.warn('no Cleared'))
    t.log('verdict2')
    await t.wait(700)
    await scrollAbs(t, page, 560, 1300)
    await t.mark('verdict2', page.getByText('Clearance', { exact: true }).locator('xpath=../..'))
    await t.wait(3500)
    await t.stop()
    await s.browser.close()
  },

  /** Signed in on the local stack: a new workspace, its key shown once, and the commands that connect a repo. */
  async workspace() {
    const s = await open()
    const { page, ctx } = s
    await localSignIn(ctx)
    await page.goto(LOCAL + '/app', { waitUntil: 'networkidle' })
    await page.getByText('New workspace').first().waitFor({ timeout: 20000 })
    await settle(page, 1500)
    const t = new Take(s, 'workspace')
    await t.start()
    await t.wait(700)
    const input = page.getByPlaceholder('my-repo')
    await t.click(input, { at: 0.2, label: 'name' })
    await t.type('blog')
    await t.wait(300)
    await t.click(page.getByRole('button', { name: 'Create workspace' }), { label: 'create' })
    await page.getByText(/ask_/).first().waitFor({ timeout: 20000 })
    t.log('created')
    await t.wait(800)
    await t.mark('key', page.getByText(/ask_/).first().locator('xpath=ancestor::div[contains(@class,"rounded")][1]'))
    await t.mark('commands', page.getByText(/airspace connect/).first().locator('xpath=ancestor::div[contains(@class,"rounded")][1]'))
    const key = (await page.getByText(/ask_[A-Za-z0-9_-]+/).first().innerText()).match(/ask_[A-Za-z0-9_-]+/)[0]
    fs.writeFileSync(path.join(DATA, 'key'), key)
    const link = page.getByRole('link', { name: /Open Tower|Tower/ }).first()
    const href = await link.getAttribute('href').catch(() => null)
    fs.writeFileSync(path.join(DATA, 'workspace'), href ?? '')
    await t.wait(4500)
    await t.stop()
    await s.browser.close()

    // Connect the blog repo to it, as the page says, and install the hooks.
    command('connect', 'uv', ['run', '--project', 'server', 'airspace', 'connect', '--root', path.join(DATA, 'blog'), '--server', `http://localhost:8810`, '--key', key])
    command('install', 'uv', ['run', '--project', 'server', 'airspace', 'install-hooks', '--root', path.join(DATA, 'blog')])
  },

  /** The workspace's Tower, live, while two sessions run through the real hooks; then a later session. */
  async wstower() {
    const href = fs.readFileSync(path.join(DATA, 'workspace'), 'utf8').trim()
    if (!href.startsWith('/w/')) throw new Error(`no workspace link: ${href}`)
    const s = await open()
    const { page, ctx } = s
    await localSignIn(ctx)
    await page.goto(LOCAL + href, { waitUntil: 'networkidle' })
    await settle(page, 1500)
    const t = new Take(s, 'wstower')
    await t.start()
    await t.wait(800)
    await session('a-start')
    t.log('a-start')
    await t.wait(3200)
    await session('b-start')
    t.log('b-start')
    await page.getByText('was held editing').first().waitFor({ timeout: 20000 })
    t.log('held')
    await t.wait(1800)
    const row = page.getByRole('button', { name: /was held at/ })
    await t.click(row, { at: 0.3, label: 'collision' })
    await t.wait(1600)
    const panel = page.locator('section[aria-label="Collision"]')
    await t.mark('panel', panel)
    await t.mark('actions', panel.getByRole('button', { name: /Release hold/ }).locator('xpath=../..'))
    await t.hover(panel.getByRole('button', { name: /Release hold/ }))
    await t.wait(900)
    await t.hover(panel.getByRole('button', { name: /Pause agent-a/ }))
    await t.wait(900)
    const box = panel.locator('textarea')
    await t.click(box, { at: 0.3, label: 'message' })
    await t.type('Use the new keyword: unicode=True', { min: 30, max: 75 })
    await t.wait(300)
    await t.click(panel.getByRole('button', { name: /Send/ }), { label: 'send' })
    t.log('sent')
    await t.wait(2200)
    await session('a-land')
    t.log('a-land')
    await t.wait(1500)
    await session('b-retry')
    t.log('b-retry')
    await page.getByText('cleared the collision').first().waitFor({ timeout: 20000 }).catch(() => {})
    t.log('cleared')
    await t.wait(1500)
    await session('b-land')
    t.log('b-land')
    await t.wait(2500)
    await t.mark('memory', page.getByRole('heading', { name: 'Memory' }).locator('xpath=..'))
    await t.mark('panel2', panel)
    await t.wait(1500)
    // A later session: agent-c is told the fix before it writes its call.
    await session('c-start')
    t.log('c-start')
    await t.wait(2500)
    await session('c-edit')
    t.log('c-edit')
    await t.wait(3000)
    await t.mark('memory2', page.getByRole('heading', { name: 'Memory' }).locator('xpath=..'))
    await t.wait(1500)
    await t.stop()
    await s.browser.close()
  },

  /** The workspace's Tower after the run: the memory list in the sidebar, with the fix on slugify. */
  async wsmemory() {
    const href = fs.readFileSync(path.join(DATA, 'workspace'), 'utf8').trim()
    const s = await open()
    const { page, ctx } = s
    await localSignIn(ctx)
    await page.goto(LOCAL + href, { waitUntil: 'networkidle' })
    await settle(page, 1500)
    const t = new Take(s, 'wsmemory')
    await t.start()
    await t.move(160, 500)
    await t.wait(600)
    const heading = page.locator('aside h2', { hasText: 'Memory' })
    const top = await heading.evaluate((el) => el.getBoundingClientRect().top)
    await t.scroll(top - 80, 1600, { el: 'aside' })
    await t.wait(500)
    await t.mark('memory', heading.locator('xpath=..'))
    await t.wait(4000)
    await t.stop()
    await s.browser.close()
  },
}
