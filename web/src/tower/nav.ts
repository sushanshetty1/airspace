// In-app navigation without a router: pushState, then tell App through popstate.

export function navigate(path: string) {
  const url = path + window.location.search
  if (url === window.location.pathname + window.location.search) return
  window.history.pushState(null, '', url)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function decode(part: string) {
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

/** The collision id in /tower/collisions/:id or /w/:workspace/collisions/:id, or null. */
export function collisionIdFrom(pathname: string) {
  const m = /^\/(?:tower|w\/[^/]+)\/collisions\/([^/]+)\/?$/.exec(pathname)
  return m ? decode(m[1]) : null
}

/** The workspace id in /w/:id and the paths under it, or null. */
export function workspaceIdFrom(pathname: string) {
  const m = /^\/w\/([^/]+)(?:\/.*)?$/.exec(pathname)
  return m ? decode(m[1]) : null
}

/** A workspace's Tower. */
export const workspacePath = (id: string) => `/w/${encodeURIComponent(id)}`

/** A collision, under the demo Tower at /tower or under a workspace's Tower. */
export const collisionPath = (id: string, base = '/tower') => `${base}/collisions/${encodeURIComponent(id)}`
