export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

/** Dispatched whenever apiFetch sees a 401 on an authenticated (non-/api/auth/) call. */
export const UNAUTHORIZED_EVENT = "eo:unauthorized"

/** Extract a user-facing message from a query/mutation error, ApiError-aware. */
export function getErrorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (error instanceof ApiError) return error.detail
  if (error instanceof Error) return error.message
  return fallback
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("eo_token")
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...Object.fromEntries(Object.entries(init?.headers ?? {})),
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const response = await fetch(path, { ...init, headers })

  if (response.status === 401 && !path.includes("/api/auth/")) {
    localStorage.removeItem("eo_token")
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    throw new ApiError(401, "Session expired")
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }

  return response.json()
}
