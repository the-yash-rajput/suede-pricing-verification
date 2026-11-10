export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function call(method, path, body) {
  const r = await fetch(API + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => null)
  if (!r.ok) throw new Error((data && data.detail) || `${r.status} ${r.statusText}`)
  return data
}

export const api = {
  verify: (req) => call('POST', '/verify', req),
  verifyInputs: (noCache) => call('POST', `/verify/inputs?no_cache=${!!noCache}`),
  inputs: () => call('GET', '/inputs'),
  shipping: (req) => call('POST', '/shipping', req),
  brands: () => call('GET', '/brands'),
  adapters: () => call('GET', '/adapters'),
  probe: (b) => call('POST', '/brands/probe', b),
  saveBrand: (b) => call('POST', '/brands', b),
  patchBrand: (id, p) => call('PATCH', `/brands/${id}`, p),
  observations: (outcome) => call('GET', `/observations${outcome ? `?outcome=${outcome}` : ''}`),
}

// evidence item path is "evidence/<run>/<brand>/<file>", served by the API at /evidence/...
export const evidenceUrl = (p) => `${API}/${p}`
