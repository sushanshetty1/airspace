import { useCallback, useEffect, useRef, useState } from 'react'
import type { AirEvent, RadarData, StateData, TowerApi } from './api'

export type Phase = 'loading' | 'ready' | 'error'
export type Conn = 'live' | 'reconnecting' | 'offline'

export type Live = {
  phase: Phase
  conn: Conn
  state: StateData | null
  radar: RadarData | null
  /** Oldest first, each id once. */
  events: AirEvent[]
  /** Bumps whenever state and radar were refetched, so dependent views can refetch too. */
  tick: number
  /** Refetch state and radar now, for example right after an action. */
  refresh: () => void
  /** Try the first load again now instead of waiting for the next attempt. */
  retry: () => void
}

const DEBOUNCE_MS = 150
const POLL_MS = 3000
const SSE_FAILURES_BEFORE_POLLING = 3
const HEALTH_MS = 5000

/**
 * Loads state, radar and events, then follows the event stream.
 * Each event triggers a debounced refetch of state and radar. The stream
 * reconnects with backoff; after three failures it falls back to polling.
 */
export function useLive(api: TowerApi): Live {
  const [state, setState] = useState<StateData | null>(null)
  const [radar, setRadar] = useState<RadarData | null>(null)
  const [events, setEvents] = useState<AirEvent[]>([])
  const [phase, setPhase] = useState<Phase>('loading')
  const [conn, setConn] = useState<Conn>('reconnecting')
  const [tick, setTick] = useState(0)
  const refreshRef = useRef<() => void>(() => {})
  const retryRef = useRef<() => void>(() => {})

  useEffect(() => {
    let alive = true
    const seen = new Set<string>()
    let lastAt = 0
    let failures = 0
    let loadAttempts = 0
    let closeStream: (() => void) | null = null
    let debounceTimer = 0
    let reconnectTimer = 0
    let pollTimer = 0
    let loadTimer = 0
    let loading = false
    let healthTimer = 0

    const addEvents = (list: AirEvent[]) => {
      const fresh = list.filter((e) => e && typeof e.id === 'string' && !seen.has(e.id))
      if (!fresh.length) return false
      for (const e of fresh) {
        seen.add(e.id)
        lastAt = Math.max(lastAt, e.at)
      }
      setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.at - b.at).slice(-400))
      return true
    }

    const fetchViews = async () => {
      const [s, r] = await Promise.all([api.state(), api.radar()])
      if (!alive) return
      setState(s)
      setRadar(r)
      setTick((t) => t + 1)
    }

    const scheduleRefetch = () => {
      window.clearTimeout(debounceTimer)
      debounceTimer = window.setTimeout(() => {
        fetchViews().catch(() => {
          // The stream or the poller reports the connection; keep the last good views.
        })
      }, DEBOUNCE_MS)
    }

    const poll = async () => {
      try {
        const list = await api.events(lastAt)
        if (!alive) return
        setConn('live')
        if (addEvents(list)) scheduleRefetch()
      } catch {
        if (!alive) return
        setConn('offline')
      }
      if (alive) pollTimer = window.setTimeout(poll, POLL_MS)
    }

    const streamFailed = () => {
      if (!alive) return
      closeStream = null
      failures += 1
      setConn('reconnecting')
      if (failures >= SSE_FAILURES_BEFORE_POLLING) {
        poll()
        return
      }
      reconnectTimer = window.setTimeout(openStream, 1000 * 2 ** (failures - 1))
    }

    // A proxy can keep a stream open after the server is gone, so check now and then.
    const checkHealth = async () => {
      if (closeStream) {
        try {
          await api.state()
        } catch {
          if (alive && closeStream) {
            closeStream()
            streamFailed()
          }
        }
      }
      if (alive) healthTimer = window.setTimeout(checkHealth, HEALTH_MS)
    }

    const openStream = () => {
      if (!alive) return
      closeStream = api.stream(lastAt, {
        onOpen: () => {
          if (!alive) return
          failures = 0
          setConn('live')
          // Catch up on anything that changed while the stream was down.
          scheduleRefetch()
        },
        onEvent: (e) => {
          if (alive && addEvents([e])) scheduleRefetch()
        },
        onError: streamFailed,
      })
    }

    const load = async () => {
      window.clearTimeout(loadTimer)
      if (loading) return
      loading = true
      try {
        const [s, r, ev] = await Promise.all([api.state(), api.radar(), api.events(0)])
        if (!alive) return
        setState(s)
        setRadar(r)
        addEvents(ev)
        setTick((t) => t + 1)
        setPhase('ready')
        openStream()
        healthTimer = window.setTimeout(checkHealth, HEALTH_MS)
      } catch {
        if (!alive) return
        loadAttempts += 1
        setPhase('error')
        setConn('offline')
        loadTimer = window.setTimeout(load, Math.min(10000, 1500 * 2 ** (loadAttempts - 1)))
      } finally {
        loading = false
      }
    }

    refreshRef.current = scheduleRefetch
    retryRef.current = () => {
      setPhase('loading')
      load()
    }
    load()

    return () => {
      alive = false
      closeStream?.()
      window.clearTimeout(debounceTimer)
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(pollTimer)
      window.clearTimeout(loadTimer)
      window.clearTimeout(healthTimer)
    }
  }, [api])

  const refresh = useCallback(() => refreshRef.current(), [])
  const retry = useCallback(() => retryRef.current(), [])

  return { phase, conn, state, radar, events, tick, refresh, retry }
}
