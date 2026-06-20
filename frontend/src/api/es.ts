import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"

export interface ClusterHealth {
  cluster_name: string
  status: string
  number_of_nodes: number
  number_of_data_nodes: number
  active_primary_shards: number
  active_shards: number
  relocating_shards: number
  initializing_shards: number
  unassigned_shards: number
}

export interface NodeInfo {
  name: string
  role: string
  ip: string
  version: string
  disk_total: number
  disk_used: number
  disk_used_percent: number
  heap_max: number
  heap_current: number
  heap_percent: number
  cpu: number
  load_1m: number
  segments_count: number
}

export interface IndexInfo {
  health: string
  status: string
  index: string
  pri: number
  rep: number
  docs_count: number
  store_size: number
  pri_store_size: number
}

export interface ShardInfo {
  index: string
  shard: number
  prirep: string
  state: string
  docs: number
  store: number
  node: string | null
  segments_count: number
}

export interface RecoveryInfo {
  index: string
  shard: number
  source_node: string
  target_node: string
  bytes_total: number
  bytes_recovered: number
  bytes_percent: string
}

export interface StorageGroup {
  name: string
  size_bytes: number
}

export interface NodeRoleCounts {
  master: number
  data: number
  coord: number
  ingest: number
  other: number
}

export interface OverviewData {
  health: ClusterHealth
  index_count: number
  nodes: NodeInfo[]
  recoveries: RecoveryInfo[]
  storage_breakdown: StorageGroup[]
  node_role_counts: NodeRoleCounts
}

export interface ShardMapData {
  nodes: NodeInfo[]
  indices: IndexInfo[]
  shards: ShardInfo[]
}

export interface Opportunity {
  type: string
  severity: string
  detail: string
  wasted_shards: number
  target_shards: number
}

export interface AnalyzedIndex {
  name: string
  health: string
  status: string
  pri_count: number
  rep_count: number
  doc_count: number
  pri_store_bytes: number
  store_bytes: number
  avg_shard_size_gb: number
  max_shard_size_gb: number
  max_segments_per_shard: number
  shard_size_cv: number
  opportunities: Opportunity[]
  opportunity_count: number
  wasted_shards: number
}

export interface AnalysisData {
  total_indices: number
  total_with_opportunities: number
  total_wasted_shards: number
  indices: AnalyzedIndex[]
}

function esPath(clusterId: number, path: string) {
  return `/api/clusters/${clusterId}/es${path}`
}

export function useClusterHealth(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "health", clusterId],
    queryFn: () => apiFetch<ClusterHealth>(esPath(clusterId!, "/health")),
    enabled: clusterId !== null,
    refetchInterval: 15_000,
  })
}

export function useOverview(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "overview", clusterId],
    queryFn: () => apiFetch<OverviewData>(esPath(clusterId!, "/overview")),
    enabled: clusterId !== null,
    refetchInterval: 15_000,
  })
}

export function useNodes(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "nodes", clusterId],
    queryFn: () => apiFetch<NodeInfo[]>(esPath(clusterId!, "/nodes")),
    enabled: clusterId !== null,
    refetchInterval: 15_000,
  })
}

export function useIndices(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "indices", clusterId],
    queryFn: () => apiFetch<IndexInfo[]>(esPath(clusterId!, "/indices")),
    enabled: clusterId !== null,
    refetchInterval: 30_000,
  })
}

export function useShards(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "shards", clusterId],
    queryFn: () => apiFetch<ShardInfo[]>(esPath(clusterId!, "/shards")),
    enabled: clusterId !== null,
    refetchInterval: 30_000,
  })
}

export function useShardMap(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "shard-map", clusterId],
    queryFn: () => apiFetch<ShardMapData>(esPath(clusterId!, "/shard-map")),
    enabled: clusterId !== null,
    refetchInterval: 30_000,
  })
}

export function useAnalysis(clusterId: number | null, problemsOnly: boolean = false) {
  return useQuery({
    queryKey: ["es", "analyze", clusterId, problemsOnly],
    queryFn: () =>
      apiFetch<AnalysisData>(
        esPath(clusterId!, `/analyze${problemsOnly ? "?problems_only=true" : ""}`),
      ),
    enabled: clusterId !== null,
    staleTime: 60_000,
  })
}

export interface ClusterSettings {
  persistent: Record<string, string>
  transient: Record<string, string>
  defaults: Record<string, string>
}

export function useClusterSettings(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "settings", clusterId],
    queryFn: () => apiFetch<ClusterSettings>(esPath(clusterId!, "/settings")),
    enabled: clusterId !== null,
  })
}

export function useUpdateSettings(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { persistent?: Record<string, string | null>; transient?: Record<string, string | null> }) =>
      apiFetch(esPath(clusterId!, "/settings"), { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["es", "settings"] }),
  })
}
