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
  progress?: string | null
  node_name?: string | null
  target_index?: string | null
  shard_number?: number | null
  from_node?: string | null
  to_node?: string | null
}

export interface JobSummary {
  total: number
  pending: number
  approved: number
  queued: number
  executing: number
  completed: number
  failed: number
  cancelled: number
  rejected: number
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
    mutationFn: (detectors?: string[]) =>
      apiFetch(jobsPath(clusterId!, "/recommend"), {
        method: "POST",
        body: JSON.stringify({ detectors: detectors ?? null }),
      }),
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

export interface ExecuteAllResult {
  queued: number
  skipped: number
}

export function useExecuteAll(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<ExecuteAllResult>(jobsPath(clusterId, "/execute-all"), { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useRelocateShard(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { index: string; shard: number; from_node: string; to_node: string }) =>
      apiFetch<Job>(jobsPath(clusterId, "/relocate"), { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["es"] }),
  })
}

export function useDrainNode(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { node: string }) =>
      apiFetch(jobsPath(clusterId, "/drain"), { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["es"] }),
  })
}

export function useCancelJob(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) =>
      apiFetch(jobsPath(clusterId, `/${jobId}/cancel`), { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function usePromoteIndex(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { source: string; target: string; alias: string; delete_source: boolean }) =>
      apiFetch<Job>(jobsPath(clusterId, "/promote"), { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useReindex(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { source: string; dest: string }) =>
      apiFetch<Job>(jobsPath(clusterId, "/reindex"), { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export interface JobConcurrency {
  max_concurrent: number
}

export function useConcurrency(clusterId: number | null) {
  return useQuery({
    queryKey: ["jobs", "concurrency", clusterId],
    queryFn: () => apiFetch<JobConcurrency>(jobsPath(clusterId!, "/concurrency")),
    enabled: clusterId !== null,
  })
}

export function useClearQueue(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch(jobsPath(clusterId, "/clear-queue"), { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

export function useClearHistory(clusterId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch(jobsPath(clusterId, "/clear-history"), { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  })
}

/** Human-readable labels for all job types (recommender-generated + operator-initiated). */
export const JOB_TYPE_LABELS: Record<string, string> = {
  reduce_shards: "Reduce Shards",
  force_merge: "Force Merge",
  relocate_shard: "Relocate Shard",
  drain_node: "Drain Node",
  split_shards: "Split Shards",
  expunge_deletes: "Expunge Deletes",
  promote_index: "Promote Index",
  reindex: "Reindex",
}
