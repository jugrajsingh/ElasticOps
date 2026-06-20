export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
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
    throw new ApiError(401, "Session expired")
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }

  return response.json()
}
