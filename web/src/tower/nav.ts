// In-app navigation without a router: pushState, then tell App through popstate.

export function navigate(path: string) {
  const url = path + window.location.search
  if (url === window.location.pathname + window.location.search) return
  window.history.pushState(null, '', url)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** The collision id in /tower/collisions/:id, or null. */
export function collisionIdFrom(pathname: string) {
  const m = /^\/tower\/collisions\/([^/]+)\/?$/.exec(pathname)
  if (!m) return null
  try {
    return decodeURIComponent(m[1])
  } catch {
    return m[1]
  }
}

export const collisionPath = (id: string) => `/tower/collisions/${encodeURIComponent(id)}`
