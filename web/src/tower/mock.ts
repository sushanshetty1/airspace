// Sample data for Tower without a server: /tower?mock=1 (the marketing story),
// ?mock=4 (four agents), ?mock=empty, ?mock=error and ?mock=loading.
// ?mock=replay plays a short sample run through the replay player.
// The mock answers actions too, so pause, release and message can be tried.

import { ApiError, type AgentState, type AirEvent, type CollisionDetail, type RadarAgent, type RadarData, type RadarSymbol, type StateData, type TowerApi } from './api'
import type { ReplayDoc, ReplayFrame } from './replay'

export type MockVariant = 'story' | 'four' | 'empty' | 'error' | 'loading' | 'replay'

export function mockVariant(search: string): MockVariant | null {
  const v = new URLSearchParams(search).get('mock')
  if (v === null) return null
  if (v === 'empty' || v === 'error' || v === 'loading' || v === 'replay') return v
  if (v === '4' || v === 'four') return 'four'
  return 'story'
}

// The story ends about two minutes before the page opens, so new events read in order.
const storyEnd = Math.floor(Date.now() / 1000) - 120
const STORY_END = 10 * 3600 + 42 * 60 + 31

/** A time in the story (10:42:31 is the hold), moved to just before now, in epoch seconds. */
function at(h: number, m: number, s: number) {
  return storyEnd + (h * 3600 + m * 60 + s - STORY_END)
}

const sym = (label: string, kind = 'function', is_test = false): RadarSymbol => ({ label, kind, is_test })

const storySymbols: Record<string, RadarSymbol> = {
  'utils.text.slugify': sym('slugify'),
  'blog.models.Post.save': sym('Post.save', 'method'),
  'tests.test_text.test_slugify': sym('test_slugify', 'function', true),
  'tags.models.Tag.save': sym('Tag.save', 'method'),
  'tests.test_models.test_post_save': sym('test_post_save', 'function', true),
  'tags.views.tag_create': sym('tag_create'),
  'blog.views.render_post': sym('render_post'),
  'blog.views.post_list': sym('post_list'),
  'tests.test_views.test_render_post': sym('test_render_post', 'function', true),
  'blog.feeds.LatestPosts.item_description': sym('item_description', 'method'),
  'blog.feeds.LatestPosts': sym('LatestPosts', 'class'),
}

const storyEdges: [string, string][] = [
  ['blog.models.Post.save', 'utils.text.slugify'],
  ['tests.test_text.test_slugify', 'utils.text.slugify'],
  ['tags.models.Tag.save', 'utils.text.slugify'],
  ['tests.test_models.test_post_save', 'blog.models.Post.save'],
  ['tags.views.tag_create', 'tags.models.Tag.save'],
  ['blog.views.post_list', 'blog.views.render_post'],
  ['tests.test_views.test_render_post', 'blog.views.render_post'],
  ['blog.feeds.LatestPosts.item_description', 'blog.views.render_post'],
  ['blog.feeds.LatestPosts', 'blog.feeds.LatestPosts.item_description'],
]

const radarA: RadarAgent = {
  id: 'agent-a',
  center: 'utils.text.slugify',
  claims: ['utils.text.slugify'],
  cone: [
    { qualname: 'blog.models.Post.save', hop: 1 },
    { qualname: 'tests.test_text.test_slugify', hop: 1 },
    { qualname: 'tags.models.Tag.save', hop: 1 },
    { qualname: 'tests.test_models.test_post_save', hop: 2 },
    { qualname: 'tags.views.tag_create', hop: 2 },
  ],
}

const radarB: RadarAgent = {
  id: 'agent-b',
  center: 'blog.views.render_post',
  claims: ['blog.views.render_post'],
  cone: [
    { qualname: 'blog.views.post_list', hop: 1 },
    { qualname: 'tests.test_views.test_render_post', hop: 1 },
    { qualname: 'blog.feeds.LatestPosts.item_description', hop: 1 },
    { qualname: 'blog.feeds.LatestPosts', hop: 2 },
  ],
}

// Two more agents for ?mock=4: one quiet, one with a cone too big to draw in full.
const fourSymbols: Record<string, RadarSymbol> = {
  'accounts.forms.SignupForm.clean': sym('SignupForm.clean', 'method'),
  'accounts.views.signup': sym('signup'),
  'tests.test_accounts.test_signup': sym('test_signup', 'function', true),
  'accounts.api.register': sym('register'),
  'search.index.build_index': sym('build_index'),
  ...Object.fromEntries(
    ['reindex_posts', 'reindex_tags', 'search_view', 'autocomplete', 'rebuild_command', 'nightly_job', 'test_build_index', 'test_reindex', 'SearchForm.clean', 'api_search', 'feed_search', 'admin_reindex'].map((n) => [
      `search.${n}`,
      sym(n, 'function', n.startsWith('test_')),
    ]),
  ),
}

const fourEdges: [string, string][] = [
  ['accounts.views.signup', 'accounts.forms.SignupForm.clean'],
  ['tests.test_accounts.test_signup', 'accounts.views.signup'],
  ['accounts.api.register', 'accounts.forms.SignupForm.clean'],
  ...['reindex_posts', 'reindex_tags', 'search_view', 'autocomplete', 'rebuild_command', 'test_build_index', 'api_search'].map((n) => [`search.${n}`, 'search.index.build_index'] as [string, string]),
  ['search.nightly_job', 'search.reindex_posts'],
  ['search.test_reindex', 'search.reindex_tags'],
  ['search.SearchForm.clean', 'search.search_view'],
  ['search.feed_search', 'search.search_view'],
  ['search.admin_reindex', 'search.rebuild_command'],
]

const radarC: RadarAgent = {
  id: 'agent-c',
  center: 'accounts.forms.SignupForm.clean',
  claims: ['accounts.forms.SignupForm.clean'],
  cone: [
    { qualname: 'accounts.views.signup', hop: 1 },
    { qualname: 'accounts.api.register', hop: 1 },
    { qualname: 'tests.test_accounts.test_signup', hop: 2 },
  ],
}

const radarD: RadarAgent = {
  id: 'agent-d',
  center: 'search.index.build_index',
  claims: ['search.index.build_index'],
  cone: [
    ...['reindex_posts', 'reindex_tags', 'search_view', 'autocomplete', 'rebuild_command', 'test_build_index', 'api_search'].map((n) => ({ qualname: `search.${n}`, hop: 1 })),
    ...['nightly_job', 'test_reindex', 'SearchForm.clean', 'feed_search', 'admin_reindex'].map((n) => ({ qualname: `search.${n}`, hop: 2 })),
  ],
}

type World = {
  state: StateData
  radar: RadarData
  events: AirEvent[]
  collisions: Record<string, CollisionDetail>
}

function agent(id: string, claims: string[], extra: Partial<AgentState> = {}): AgentState {
  return { id, paused: false, status: 'active', tasks: [`${id}-task`], claims, held: false, ...extra }
}

function storyWorld(four: boolean): World {
  const collision: CollisionDetail = {
    id: 'c_0007',
    at: at(10, 42, 31),
    kind: 'contract',
    symbol: 'utils.text.slugify',
    caller: 'blog.views.render_post',
    path: ['blog.views.render_post', 'utils.text.slugify'],
    held_agent: 'agent-b',
    held_task: 'agent-b-task',
    owner_agent: 'agent-a',
    owner_task: 'agent-a-task',
    old_sig: 'slugify(value, allow_unicode=False)',
    new_sig: 'slugify(value, *, unicode=False)',
    resolution: 'held',
  }
  const ev = (n: number, t: number, kind: AirEvent['kind'], who: string, text: string, code: string): AirEvent => ({ id: `e${n}`, at: t, kind, agent: who, task: `${who}-task`, text, code })
  const events: AirEvent[] = [
    ev(1, at(10, 42, 3), 'plan', 'agent-a', 'filed a plan for', 'utils.text.slugify'),
    ev(2, at(10, 42, 5), 'plan', 'agent-b', 'filed a plan for', 'blog.views.render_post'),
    ev(3, at(10, 42, 19), 'cleared', 'agent-a', 'was cleared to edit', 'utils.text.slugify'),
    ev(4, at(10, 42, 20), 'contract', 'agent-a', 'changed the signature of', 'utils.text.slugify'),
    ev(5, at(10, 42, 31), 'hold', 'agent-b', 'was held editing', 'blog.views.render_post'),
    ev(6, at(10, 42, 31.2), 'briefed', 'agent-b', 'got the new signature of', 'utils.text.slugify'),
  ]
  const agents = [agent('agent-a', ['utils.text.slugify']), agent('agent-b', ['blog.views.render_post'], { held: true })]
  const radarAgents = [radarA, radarB]
  if (four) {
    agents.push(agent('agent-c', ['accounts.forms.SignupForm.clean']), agent('agent-d', ['search.index.build_index']))
    radarAgents.push(radarC, radarD)
    events.splice(2, 0, ev(10, at(10, 42, 8), 'plan', 'agent-c', 'filed a plan for', 'accounts.forms.SignupForm.clean'), ev(11, at(10, 42, 12), 'plan', 'agent-d', 'filed a plan for', 'search.index.build_index'))
  }
  return {
    state: {
      now: Date.now() / 1000,
      repo: 'blog-api',
      agents,
      collisions: [{ id: collision.id, at: collision.at, kind: collision.kind, symbol: collision.symbol, held_agent: collision.held_agent, owner_agent: collision.owner_agent, resolution: 'held' }],
    },
    radar: {
      agents: radarAgents,
      symbols: four ? { ...storySymbols, ...fourSymbols } : storySymbols,
      edges: four ? [...storyEdges, ...fourEdges] : storyEdges,
      collision: { id: collision.id, symbol: collision.symbol, caller: collision.caller, held_agent: collision.held_agent, owner_agent: collision.owner_agent, resolution: 'held' },
    },
    events,
    collisions: { [collision.id]: collision },
  }
}

function emptyWorld(): World {
  return { state: { now: Date.now() / 1000, repo: 'blog-api', agents: [], collisions: [] }, radar: { agents: [], symbols: {}, edges: [], collision: null }, events: [], collisions: {} }
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))
const never = <T,>() => new Promise<T>(() => {})

export function createMockApi(variant: MockVariant): TowerApi {
  if (variant === 'loading') {
    return { state: never, radar: never, events: never, collision: never, pause: never, resume: never, message: never, release: never, stream: () => () => {} }
  }
  if (variant === 'error') {
    const fail = () => Promise.reject(new ApiError(0, 'The Airspace server did not answer.'))
    return {
      state: fail,
      radar: fail,
      events: fail,
      collision: fail,
      pause: fail,
      resume: fail,
      message: fail,
      release: fail,
      stream: (_since, h) => {
        const t = window.setTimeout(h.onError, 50)
        return () => window.clearTimeout(t)
      },
    }
  }

  const world = variant === 'empty' ? emptyWorld() : storyWorld(variant === 'four')
  const listeners = new Set<(e: AirEvent) => void>()
  let seq = 100

  const emit = (kind: AirEvent['kind'], who: string, text: string, code: string) => {
    const e: AirEvent = { id: `e${seq++}`, at: Date.now() / 1000, kind, agent: who, task: `${who}-task`, text, code }
    world.events.push(e)
    world.state.now = e.at
    listeners.forEach((l) => l(e))
  }

  const setResolution = (id: string, resolution: CollisionDetail['resolution']) => {
    const c = world.collisions[id]
    c.resolution = resolution
    const summary = world.state.collisions.find((s) => s.id === id)
    if (summary) summary.resolution = resolution
    if (world.radar.collision?.id === id) world.radar.collision.resolution = resolution
    const held = world.state.agents.find((a) => a.id === c.held_agent)
    if (held) held.held = Object.values(world.collisions).some((x) => x.held_agent === held.id && x.resolution === 'held')
  }

  const setPaused = (id: string, paused: boolean) => {
    const a = world.state.agents.find((x) => x.id === id)
    if (!a || a.paused === paused) return
    a.paused = paused
    emit(paused ? 'paused' : 'resumed', id, paused ? 'was paused from' : 'was resumed from', 'Tower')
  }

  return {
    state: async () => (await wait(120), clone(world.state)),
    radar: async () => (await wait(120), clone(world.radar)),
    events: async (since) => (await wait(80), clone(world.events.filter((e) => e.at > since))),
    collision: async (id) => (await wait(100), world.collisions[id] ? clone(world.collisions[id]) : null),
    pause: async (id) => {
      await wait(250)
      setPaused(id, true)
    },
    resume: async (id) => {
      await wait(250)
      setPaused(id, false)
    },
    message: async (id, text) => {
      await wait(300)
      if (!text.trim() || text.length > 500) throw new ApiError(422, 'Messages are 1 to 500 characters.')
      emit('message', id, 'got a message from', 'Tower')
      // As in the story: the held agent reads the message, uses the new signature and is cleared.
      const open = Object.values(world.collisions).find((c) => c.held_agent === id && c.resolution === 'held')
      if (open) {
        window.setTimeout(() => {
          if (open.resolution !== 'held') return
          emit('cleared', id, 'was cleared to edit', open.caller ?? open.symbol)
          setResolution(open.id, 'resolved')
          emit('resolved', id, 'cleared the collision at', open.symbol)
        }, 2200)
      }
      return `m${seq}`
    },
    release: async (cid) => {
      await wait(250)
      const c = world.collisions[cid]
      if (!c || c.resolution !== 'held') return false
      setResolution(cid, 'released')
      emit('released', c.held_agent, 'had a hold released at', c.symbol)
      return true
    },
    stream: (since, h) => {
      const l = (e: AirEvent) => {
        if (e.at > since) h.onEvent(e)
      }
      listeners.add(l)
      const t = window.setTimeout(h.onOpen, 30)
      return () => {
        window.clearTimeout(t)
        listeners.delete(l)
      }
    },
  }
}

/** ?mock=replay: the story as a recorded run, from the two plans to agent-b's cleared retry. */
export function mockReplay(): ReplayDoc {
  const story = storyWorld(false)
  const t0 = at(10, 42, 3)
  const ev = (n: number, dt: number, kind: AirEvent['kind'], who: string, text: string, code: string): AirEvent => ({ id: `r${n}`, at: t0 + dt, kind, agent: who, task: `${who}-task`, text, code })
  const events: AirEvent[] = [
    ev(1, 0, 'plan', 'agent-a', 'filed a plan for', 'utils.text.slugify'),
    ev(2, 2, 'plan', 'agent-b', 'filed a plan for', 'blog.views.render_post'),
    ev(3, 16, 'cleared', 'agent-a', 'was cleared to edit', 'utils.text.slugify'),
    ev(4, 17, 'contract', 'agent-a', 'changed the signature of', 'utils.text.slugify'),
    ev(5, 28, 'hold', 'agent-b', 'was held editing', 'blog.views.render_post'),
    ev(6, 28.2, 'briefed', 'agent-b', 'got the new signature of', 'utils.text.slugify'),
    ev(7, 51, 'cleared', 'agent-b', 'was cleared to edit', 'blog.views.render_post'),
    ev(8, 51.1, 'resolved', 'agent-b', 'cleared the collision at', 'utils.text.slugify'),
  ]
  const c = { ...story.collisions.c_0007, at: events[4].at }
  const a = agent('agent-a', ['utils.text.slugify'])
  const b = agent('agent-b', ['blog.views.render_post'])
  const frame = (e: AirEvent, agents: AgentState[], radarAgents: RadarAgent[], res: CollisionDetail['resolution'] | null): ReplayFrame => ({
    at: e.at,
    state: {
      now: e.at,
      repo: 'blog-api',
      agents: clone(agents),
      collisions: res ? [{ id: c.id, at: c.at, kind: c.kind, symbol: c.symbol, held_agent: c.held_agent, owner_agent: c.owner_agent, resolution: res }] : [],
    },
    radar: {
      agents: clone(radarAgents),
      symbols: storySymbols,
      edges: storyEdges,
      collision: res ? { id: c.id, symbol: c.symbol, caller: c.caller, held_agent: c.held_agent, owner_agent: c.owner_agent, resolution: res } : null,
    },
  })
  const frames = [
    frame(events[0], [a], [radarA], null),
    frame(events[1], [a, b], [radarA, radarB], null),
    frame(events[2], [a, b], [radarA, radarB], null),
    frame(events[3], [a, b], [radarA, radarB], null),
    frame(events[5], [a, { ...b, held: true }], [radarA, radarB], 'held'),
    frame(events[7], [a, b], [radarA, radarB], 'resolved'),
  ]
  return { version: 1, recorded_at: events[7].at + 5, events, frames, collisions: { [c.id]: { ...c, resolution: 'resolved' } } }
}
