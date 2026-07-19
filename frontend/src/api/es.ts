import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "./client"
import { useClusterContext } from "@/context/ClusterContext"

/**
 * The single client-side auto-refresh cadence (ms) every snapshot hook re-reads the DB cache on,
 * chosen via the TopBar dropdown. Returns `false` when the user picked "Off" (freeze — no polling).
 * Note: this only re-reads the cheap cached snapshot; it never re-polls the live cluster. Only the
 * explicit force-refresh button (`useRefreshSnapshots`) hits Elasticsearch.
 */
function useAutoRefetch(): number | false {
  const { refreshInterval } = useClusterContext()
  return refreshInterval > 0 ? refreshInterval : false
}

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

/**
 * Every `/es/*` read endpoint now wraps its payload in this envelope so the UI can show staleness.
 * `fetched_at` is a naive UTC ISO string (no `Z` suffix) — parse it as UTC, see `parseUtc`.
 */
export interface Cached<T> {
  data: T
  fetched_at: string
  stale_seconds: number
  next_poll_in: number | null
}

/** Snapshot freshness metadata, surfaced to the TopBar staleness indicator. */
export interface SnapshotMeta {
  fetched_at: string
  stale_seconds: number
  next_poll_in: number | null
}

/** A node row precomputed server-side with its shard count and tier label. */
export interface NodeInfoEx extends NodeInfo {
  shard_count: number
  tier: string
}

/** One shard chip in a grid cell (the minimal payload the chip needs). */
export interface ShardCell {
  shard: number
  prirep: string
  state: string
  store: number
  docs: number
  segments_count: number
}

export interface ShardMapColumn {
  name: string
  short: string
  tier: string
  disk_used_percent: number
}

export interface ShardMapRow {
  index: string
  pri_store_size: number
  health: string
}

/** Precomputed grid: columns = `data_nodes`, rows = `indices`, cell = `cells["<index> <node>"]`. */
export interface ShardMapGrid {
  data_nodes: ShardMapColumn[]
  indices: ShardMapRow[]
  cells: Record<string, ShardCell[]>
}

/** Per-data-node aggregate at a pivot tree node. */
export interface PivotNodeAgg {
  node: string
  shard_count: number
  size: number
}

/** A node in the dynamic-depth pivot rollup tree. */
export interface PivotNode {
  key: string
  label: string
  depth: number
  total_size: number
  total_docs: number
  shard_count: number
  index_count: number
  per_node: PivotNodeAgg[]
  children: PivotNode[]
  is_leaf: boolean
}

export interface PivotColumn {
  name: string
  short: string
  disk_used_percent: number
}

/** Precomputed dynamic-depth pivot tree with per-data-node aggregates. */
export interface PivotTree {
  separator: string
  data_nodes: PivotColumn[]
  max_cell_size: number
  roots: PivotNode[]
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

/**
 * Parse the snapshot `fetched_at` string. The backend serializes a naive UTC datetime (no `Z`), so
 * we append `Z` when no timezone designator is present to avoid local-time misinterpretation.
 */
export function parseUtc(iso: string): number {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : `${iso}Z`).getTime()
}

/** Extract just the freshness metadata from a wrapped response. */
function pickMeta<T>(r: Cached<T>): SnapshotMeta {
  return { fetched_at: r.fetched_at, stale_seconds: r.stale_seconds, next_poll_in: r.next_poll_in }
}

export function useClusterHealth(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "health", clusterId],
    queryFn: () => apiFetch<Cached<ClusterHealth>>(esPath(clusterId!, "/health")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function useOverview(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "overview", clusterId],
    queryFn: () => apiFetch<Cached<OverviewData>>(esPath(clusterId!, "/overview")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function useNodes(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "nodes", clusterId],
    queryFn: () => apiFetch<Cached<NodeInfoEx[]>>(esPath(clusterId!, "/nodes")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function useShards(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "shards", clusterId],
    queryFn: () => apiFetch<Cached<ShardInfo[]>>(esPath(clusterId!, "/shards")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function useShardMap(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "shard-map", clusterId],
    queryFn: () => apiFetch<Cached<ShardMapGrid>>(esPath(clusterId!, "/shard-map")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function usePivot(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "pivot", clusterId],
    queryFn: () => apiFetch<Cached<PivotTree>>(esPath(clusterId!, "/pivot")),
    enabled: clusterId !== null,
    refetchInterval,
    select: (r) => r.data,
  })
}

export function useAnalysis(clusterId: number | null, problemsOnly: boolean = false) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "analyze", clusterId, problemsOnly],
    queryFn: () =>
      apiFetch<Cached<AnalysisData>>(
        esPath(clusterId!, `/analyze${problemsOnly ? "?problems_only=true" : ""}`),
      ),
    enabled: clusterId !== null,
    refetchInterval,
    staleTime: 60_000,
    select: (r) => r.data,
  })
}

/**
 * Surface snapshot freshness for the TopBar staleness indicator. Reads the lightweight `health`
 * snapshot on the single client auto-refresh cadence; the query's `dataUpdatedAt` drives the
 * TopBar "next in Ns" countdown so it always matches the chosen interval.
 */
export function useSnapshotMeta(clusterId: number | null) {
  const refetchInterval = useAutoRefetch()
  return useQuery({
    queryKey: ["es", "health", clusterId],
    queryFn: () => apiFetch<Cached<ClusterHealth>>(esPath(clusterId!, "/health")),
    enabled: clusterId !== null,
    refetchInterval,
    select: pickMeta,
  })
}

/**
 * Force a server-side snapshot refresh (`POST /es/refresh`). The backend rebuilds every kind from
 * one raw ES fetch, so we invalidate all `es` queries on success to pull the fresh snapshots.
 */
export function useRefreshSnapshots(clusterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiFetch<{ cluster_id: number; kind: string | null; fetched_at: string | null }>(
        esPath(clusterId!, "/refresh"),
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["es"] }),
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

export interface RebalanceSuggestion {
  index: string
  shard: number
  from_node: string
  to_node: string
  size_bytes: number
}

export function useRebalanceSuggestions(clusterId: number | null) {
  return useQuery({
    queryKey: ["es", "rebalance-suggestions", clusterId],
    queryFn: () =>
      apiFetch<{ suggestions: RebalanceSuggestion[] }>(esPath(clusterId!, "/rebalance-suggestions")),
    enabled: clusterId !== null,
  })
}
