export type Params = Record<string, string | number | null | undefined>

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [k, v] of Object.entries(params)) {
    if (v !== '' && v != null) url.searchParams.set(k, String(v))
  }
  const res = await fetch(url, { signal })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, `${detail} (${res.status})`)
  }
  return res.json() as Promise<T>
}
