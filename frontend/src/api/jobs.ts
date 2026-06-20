import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"

export interface Job {
  id: number
  run_id: number
  cluster_id: number
  index_name: string
  job_type: string
  tier: number
  severity: string
  detail: string
  current_shards: number
  target_shards: number
  current_replicas: number
  pri_store_bytes: number
  doc_count: number
  estimated_savings_shards: number
  status: string
  approved_at: string | null
  executed_at: string | null
  completed_at: string | null
  task_id: string | null
  error_message: string | null
  created_at: string
}

export interface JobSummary {
  total: number
  pending: number
  approved: number
  executing: number
  completed: number
  failed: number
}

function jobsPath(clusterId: number, path: string = "") {
  return `/api/clusters/${clusterId}/jobs${path}`
}

export function useJobs(clusterId: number | null, status?: string) {
  return useQuery({
    queryKey: ["jobs", clusterId, status],
    queryFn: () =>
      apiFetch<Job[]>(jobsPath(clusterId!, status ? `?status=${status}` : "")),
    enabled: clusterId !== null,
    refetchInterval: 5_000,
  })
}

export function useJobSummary(clusterId: number | null) {
  return useQuery({
    queryKey: ["jobs", "summary", clusterId],
    queryFn: () => apiFetch<JobSummary>(jobsPath(clusterId!, "/summary")),
    enabled: clusterId !== null,
    refetchInterval: 5_000,
  })
}

export function useRecommend(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch(jobsPath(clusterId!, "/recommend"), { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}

export function useApproveJob(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) =>
      apiFetch(jobsPath(clusterId!, `/${jobId}/approve`), { method: "PUT" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useRejectJob(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) =>
      apiFetch(jobsPath(clusterId!, `/${jobId}/reject`), { method: "PUT" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useExecuteJob(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) =>
      apiFetch(jobsPath(clusterId!, `/${jobId}/execute`), { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useBulkApprove(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (tier?: number) =>
      apiFetch(jobsPath(clusterId!, `/bulk-approve${tier !== undefined ? `?tier=${tier}` : ""}`), { method: "PUT" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}
