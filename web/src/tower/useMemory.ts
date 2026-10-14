import { useCallback, useEffect, useState } from 'react'
import type { MemoryItem, TowerApi } from './api'

export type Memory = {
  /** undefined while the first answer is on its way; null when the server has no memory. */
  items: MemoryItem[] | null | undefined
  /** The last fetch failed; the items shown are the last good ones. */
  failed: boolean
  reload: () => void
}

/** The newest notes and fixes, fetched again whenever `tick` moves (each live event bumps it). */
export function useRecentMemory(api: TowerApi, tick: number, limit = 20): Memory {
  const [items, setItems] = useState<MemoryItem[] | null | undefined>(undefined)
  const [failed, setFailed] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    api
      .recentMemory(limit)
      .then((list) => {
        if (!alive) return
        setItems(list === null ? null : [...list].sort((a, b) => b.at - a.at))
        setFailed(false)
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [api, tick, limit, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { items, failed, reload }
}
