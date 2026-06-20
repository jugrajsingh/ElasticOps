import { useMutation } from "@tanstack/react-query"
import { apiFetch } from "./client"

export interface RestResponse {
  [key: string]: unknown
}

export function useRestProxy(clusterId: number | null) {
  return useMutation({
    mutationFn: (req: { method: string; path: string; body?: string }) => {
      let parsedBody: Record<string, unknown> | undefined
      if (req.body && req.body.trim()) {
        parsedBody = JSON.parse(req.body)
      }
      return apiFetch<RestResponse>(`/api/clusters/${clusterId}/es/rest`, {
        method: "POST",
        body: JSON.stringify({ method: req.method, path: req.path, body: parsedBody }),
      })
    },
  })
}
