import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"

export interface Cluster {
  id: number
  name: string
  url: string
  username: string
  verify_ssl: boolean
  is_active: boolean
  created_at: string
  read_only?: boolean
}

export interface ClusterCreate {
  name: string
  url: string
  username?: string
  password?: string
  verify_ssl?: boolean
  read_only?: boolean
  is_active?: boolean
}

export function useClusters() {
  return useQuery({
    queryKey: ["clusters"],
    queryFn: () => apiFetch<Cluster[]>("/api/clusters"),
    enabled: !!localStorage.getItem("eo_token"),
  })
}

export function useCreateCluster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ClusterCreate) =>
      apiFetch<Cluster>("/api/clusters", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: (created) => {
      // Add the new cluster to the cached list synchronously so the selector updates
      // immediately (don't depend on the refetch landing), then reconcile with the server.
      queryClient.setQueryData<Cluster[]>(["clusters"], (old) => [...(old ?? []), created])
      queryClient.invalidateQueries({ queryKey: ["clusters"] })
    },
  })
}

export function useUpdateCluster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClusterCreate> }) =>
      apiFetch<Cluster>("/api/clusters/" + id, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["clusters"] }),
  })
}

export function useDeleteCluster() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch("/api/clusters/" + id, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["clusters"] }),
  })
}
