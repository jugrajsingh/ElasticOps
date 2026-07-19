import { useState, useMemo, useRef, useEffect } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useClusterContext } from "@/context/ClusterContext"
import {
  useShardMap,
  usePivot,
  useClusterHealth,
  useRebalanceSuggestions,
  type ShardCell,
  type ShardMapGrid,
  type PivotTree,
  type PivotNode,
  type RebalanceSuggestion,
} from "@/api/es"
import { useRelocateShard, useJobs } from "@/api/jobs"
import { getErrorMessage } from "@/api/client"
import { formatBytes, formatPercent, diskColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import QueryError from "@/components/QueryError"

type Mode = "grid" | "pivot"

type SelectedShard = {
  index: string
  shard: number
  prirep: string
  node: string
  state: string
  store: number
  docs: number
  segments_count: number
}

const NODE_COL_WIDTH = 100
const INDEX_COL_WIDTH = 280
const GRID_ROW_HEIGHT = 28

export default function ShardMap() {
  const { activeCluster } = useClusterContext()
  const { data: grid, isError: gridError, error: gridErrorObj, refetch: refetchGrid } = useShardMap(activeCluster?.id ?? null)
  const { data: pivot, isError: pivotError, error: pivotErrorObj, refetch: refetchPivot } = usePivot(activeCluster?.id ?? null)
  const { data: health } = useClusterHealth(activeCluster?.id ?? null)
  const { data: rebalanceData } = useRebalanceSuggestions(activeCluster?.id ?? null)
  const [mode, setMode] = useState<Mode>("grid")
  const [filter, setFilter] = useState("")
  const [nodeFilter, setNodeFilter] = useState<"all" | "hot" | "warm">("all")
  const [selectedShard, setSelectedShard] = useState<SelectedShard | null>(null)

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }

  const clusterStatus = health?.status?.toUpperCase() ?? "UNKNOWN"
  const dataNodeNames = (grid?.data_nodes ?? []).map((n) => n.name)
  const suggestions = rebalanceData?.suggestions ?? []

  return (
    <div className="flex flex-col h-full">
      {/* Header with mode toggle */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-eo-border bg-eo-surface/50">
        <div className="flex gap-0">
          <button
            onClick={() => setMode("grid")}
            className={cn(
              "px-3 py-1.5 text-xs font-mono border-b-2 transition-colors",
              mode === "grid" ? "border-eo-amber text-eo-amber" : "border-transparent text-eo-stone hover:text-eo-cream",
            )}
          >Grid</button>
          <button
            onClick={() => setMode("pivot")}
            className={cn(
              "px-3 py-1.5 text-xs font-mono border-b-2 transition-colors",
              mode === "pivot" ? "border-eo-amber text-eo-amber" : "border-transparent text-eo-stone hover:text-eo-cream",
            )}
          >Pivot</button>
        </div>
        <input
          type="text"
          placeholder="Filter indices..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-48 bg-eo-bg border border-eo-border rounded px-2 py-1 text-xs font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
        />
        {mode === "grid" && (
          <select
            value={nodeFilter}
            onChange={(e) => setNodeFilter(e.target.value as "all" | "hot" | "warm")}
            className="bg-eo-bg border border-eo-border rounded px-2 py-1 text-xs font-mono text-eo-cream focus:border-eo-amber focus:outline-none"
          >
            <option value="all">All nodes</option>
            <option value="hot">Hot tier</option>
            <option value="warm">Warm tier</option>
          </select>
        )}
        <span className="text-xs font-mono text-eo-stone ml-auto">
          Active: {health?.active_shards ?? "—"} · Relocating: {health?.relocating_shards ?? "—"} · {clusterStatus}
        </span>
      </div>

      {/* Content */}
      <div className="flex flex-1 min-h-0 relative">
        <div className={cn("flex-1 min-h-0", selectedShard && "mr-[400px]")}>
          {mode === "grid" ? (
            grid ? (
              <GridMode grid={grid} filter={filter} nodeFilter={nodeFilter} onSelectShard={setSelectedShard} />
            ) : gridError ? (
              <QueryError message={getErrorMessage(gridErrorObj)} onRetry={refetchGrid} />
            ) : (
              <SnapshotPending label="shard map" />
            )
          ) : pivot ? (
            <PivotMode tree={pivot} filter={filter} />
          ) : pivotError ? (
            <QueryError message={getErrorMessage(pivotErrorObj)} onRetry={refetchPivot} />
          ) : (
            <SnapshotPending label="pivot" />
          )}
        </div>

        {/* Shard detail panel */}
        {selectedShard && (
          <ShardDetailPanel
            shard={selectedShard}
            dataNodeNames={dataNodeNames}
            clusterId={activeCluster.id}
            readOnly={activeCluster.read_only ?? false}
            onClose={() => setSelectedShard(null)}
          />
        )}
      </div>

      {/* Rebalance suggestions — hidden when read-only or no suggestions */}
      {!activeCluster.read_only && suggestions.length > 0 && (
        <RebalanceSuggestionsPanel
          suggestions={suggestions}
          clusterId={activeCluster.id}
        />
      )}

      {/* Footer status bar */}
      <div className="h-8 flex items-center px-4 border-t border-eo-border bg-eo-surface/50 text-[10px] font-mono text-eo-muted gap-4">
        <span>{mode === "grid" ? "Grid Mode" : "Pivot Mode"}</span>
        <span>&middot;</span>
        <span>{(mode === "grid" ? grid?.indices.length : pivot?.roots.length) ?? 0} {mode === "grid" ? "indices" : "groups"}</span>
        <span>&middot;</span>
        <span>{(grid?.data_nodes.length ?? 0)} data nodes</span>
        <span>&middot;</span>
        <span>CLUSTER: {clusterStatus}</span>
      </div>
    </div>
  )
}

/** Thin non-blocking placeholder shown while a snapshot kind hasn't loaded yet. */
function SnapshotPending({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full text-eo-muted text-xs font-mono">
      Loading {label} snapshot…
    </div>
  )
}

/* ============ Rebalance Suggestions Panel ============ */

function RebalanceSuggestionsPanel({ suggestions, clusterId }: {
  suggestions: RebalanceSuggestion[]
  clusterId: number
}) {
  const relocate = useRelocateShard(clusterId)
  const [relocating, setRelocating] = useState<string | null>(null)

  function handleRelocate(s: RebalanceSuggestion) {
    const key = `${s.index}-${s.shard}-${s.from_node}`
    setRelocating(key)
    relocate.mutate(
      { index: s.index, shard: s.shard, from_node: s.from_node, to_node: s.to_node },
      { onSettled: () => setRelocating(null) },
    )
  }

  return (
    <div className="border-t border-eo-border bg-eo-surface/30 px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-mono text-eo-muted uppercase tracking-wider">
          Rebalance Suggestions
        </span>
        <span className="text-[10px] font-mono text-eo-amber bg-eo-amber/10 px-1.5 py-0.5 rounded">
          {suggestions.length}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s) => {
          const key = `${s.index}-${s.shard}-${s.from_node}`
          const isPending = relocating === key
          return (
            <div
              key={key}
              className="flex items-center gap-2 bg-eo-bg border border-eo-border rounded px-3 py-1.5 text-[11px] font-mono"
            >
              <span className="text-eo-cream truncate max-w-[200px]" title={s.index}>{s.index}</span>
              <span className="text-eo-muted">[{s.shard}]</span>
              <span className="text-eo-stone">{s.from_node}</span>
              <span className="text-eo-muted">→</span>
              <span className="text-eo-stone">{s.to_node}</span>
              <span className="text-eo-muted">{formatBytes(s.size_bytes)}</span>
              <button
                onClick={() => handleRelocate(s)}
                disabled={isPending || relocate.isPending}
                className={cn(
                  "ml-1 px-2 py-0.5 rounded text-[10px] border transition-colors",
                  isPending || relocate.isPending
                    ? "bg-eo-amber/10 text-eo-amber/40 border-eo-amber/20 cursor-not-allowed"
                    : "bg-eo-amber/20 text-eo-amber border-eo-amber/40 hover:bg-eo-amber/30 cursor-pointer",
                )}
              >
                {isPending ? "…" : "Relocate"}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ============ Shard Detail Panel ============ */

function ShardDetailPanel({ shard, dataNodeNames, clusterId, readOnly, onClose }: {
  shard: SelectedShard
  dataNodeNames: string[]
  clusterId: number
  readOnly: boolean
  onClose: () => void
}) {
  const otherNodes = dataNodeNames.filter((n) => n !== shard.node)
  const [targetNode, setTargetNode] = useState("")
  const [confirming, setConfirming] = useState(false)
  const [relocatedJobId, setRelocatedJobId] = useState<number | null>(null)
  const relocate = useRelocateShard(clusterId)
  const { data: jobs } = useJobs(clusterId)

  // Clear tracked job when the selected shard changes
  useEffect(() => {
    setRelocatedJobId(null)
    setTargetNode("")
    setConfirming(false)
  }, [shard.index, shard.shard, shard.node])

  const trackedJob = relocatedJobId !== null
    ? (jobs ?? []).find((j) => j.id === relocatedJobId) ?? null
    : null

  function handleRelocate() {
    if (!targetNode) return
    relocate.mutate(
      { index: shard.index, shard: shard.shard, from_node: shard.node, to_node: targetNode },
      {
        onSuccess: (data) => {
          setRelocatedJobId(data.id)
          setConfirming(false)
          setTargetNode("")
        },
      },
    )
  }

  return (
    <div className="fixed top-0 right-0 h-full w-[400px] bg-eo-bg border-l border-eo-border z-30 flex flex-col shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-eo-border bg-eo-surface/50">
        <div className="flex flex-col gap-1">
          <span className="text-sm font-mono text-eo-cream truncate max-w-[300px]">{shard.index}</span>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-eo-stone">Shard #{shard.shard}</span>
            <span className={cn(
              "text-[10px] font-mono px-1.5 py-0.5 rounded",
              shard.prirep === "p"
                ? "bg-eo-amber/20 text-eo-amber border border-eo-amber/40"
                : "bg-eo-stone/20 text-eo-stone border border-eo-stone/40",
            )}>
              {shard.prirep === "p" ? "Primary" : "Replica"}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-eo-muted hover:text-eo-cream transition-colors"
        >
          <span className="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>

      {/* Metrics */}
      <div className="flex-1 overflow-y-auto p-4">
        <h3 className="text-xs font-mono text-eo-muted uppercase mb-3">Metrics</h3>
        <div className="space-y-2">
          <MetricRow label="State" value={shard.state} highlight={shard.state !== "STARTED"} />
          <MetricRow label="Node" value={shard.node} />
          <MetricRow label="Size" value={formatBytes(shard.store)} />
          <MetricRow label="Docs" value={String(shard.docs)} />
          <MetricRow label="Segments" value={String(shard.segments_count)} highlight={shard.segments_count > 10} />
        </div>

        {/* Actions */}
        <h3 className="text-xs font-mono text-eo-muted uppercase mt-6 mb-3">Actions</h3>
        {readOnly ? (
          <p className="text-[10px] font-mono text-eo-muted">Cluster is read-only — relocation disabled.</p>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="text-[10px] font-mono text-eo-stone block mb-1">Relocate to...</label>
              <select
                className="w-full bg-eo-surface border border-eo-border rounded px-2 py-1.5 text-xs font-mono text-eo-cream focus:border-eo-amber focus:outline-none"
                value={targetNode}
                onChange={(e) => { setTargetNode(e.target.value); setConfirming(false) }}
                disabled={relocate.isPending}
              >
                <option value="" disabled>Select target node</option>
                {otherNodes.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>

            {relocate.isError && (
              <p className="text-[10px] font-mono text-eo-brick">
                {relocate.error instanceof Error ? relocate.error.message : "Relocation failed."}
              </p>
            )}

            {!confirming ? (
              <button
                className={cn(
                  "w-full px-3 py-1.5 text-xs font-mono rounded border transition-colors",
                  !targetNode || relocate.isPending
                    ? "bg-eo-amber/10 text-eo-amber/40 border-eo-amber/20 cursor-not-allowed"
                    : "bg-eo-amber/20 text-eo-amber border-eo-amber/40 hover:bg-eo-amber/30 cursor-pointer",
                )}
                disabled={!targetNode || relocate.isPending}
                onClick={() => setConfirming(true)}
              >
                Relocate Shard
              </button>
            ) : (
              <div className="flex gap-2">
                <button
                  className={cn(
                    "flex-1 px-3 py-1.5 text-xs font-mono rounded border transition-colors",
                    relocate.isPending
                      ? "bg-eo-brick/10 text-eo-brick/40 border-eo-brick/20 cursor-not-allowed"
                      : "bg-eo-brick/20 text-eo-brick border-eo-brick/40 hover:bg-eo-brick/30 cursor-pointer",
                  )}
                  disabled={relocate.isPending}
                  onClick={handleRelocate}
                >
                  {relocate.isPending ? "Relocating…" : "Confirm relocate?"}
                </button>
                <button
                  className="flex-1 px-3 py-1.5 text-xs font-mono rounded border bg-eo-surface text-eo-stone border-eo-border hover:text-eo-cream transition-colors"
                  disabled={relocate.isPending}
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </button>
              </div>
            )}

            {trackedJob && (
              <div className={cn(
                "mt-3 p-3 rounded border text-[10px] font-mono space-y-1",
                trackedJob.status === "executing"
                  ? "bg-eo-amber/10 border-eo-amber/30"
                  : trackedJob.status === "completed"
                    ? "bg-eo-sage/10 border-eo-sage/30"
                    : "bg-eo-brick/10 border-eo-brick/30",
              )}>
                <div className="flex items-center justify-between">
                  <span className="text-eo-muted uppercase">Job #{trackedJob.id}</span>
                  <span className={cn(
                    "px-1.5 py-0.5 rounded uppercase",
                    trackedJob.status === "executing"
                      ? "text-eo-amber"
                      : trackedJob.status === "completed"
                        ? "text-eo-sage"
                        : "text-eo-brick",
                  )}>
                    {trackedJob.status}
                  </span>
                </div>
                {trackedJob.status === "executing" && trackedJob.progress && (
                  <div className="text-eo-cream">Relocating: {trackedJob.progress}</div>
                )}
                {trackedJob.status === "completed" && (
                  <div className="text-eo-sage">Relocation completed.</div>
                )}
                {trackedJob.status === "failed" && (
                  <div className="text-eo-brick">
                    {trackedJob.error_message ?? "Relocation failed."}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function MetricRow({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 px-3 rounded bg-eo-surface/50">
      <span className="text-[10px] font-mono text-eo-muted uppercase">{label}</span>
      <span className={cn(
        "text-xs font-mono",
        highlight ? "text-eo-terracotta" : "text-eo-cream",
      )}>{value}</span>
    </div>
  )
}

/* ============ Grid Mode ============ */
//
// Columns (`data_nodes`) and rows (`indices`) come pre-filtered + pre-sorted from the precomputed
// `shardmap` snapshot. Each cell reads `cells["<index> <node>"]` in O(1) — no client-side grouping.
// Rows are virtualized with `useVirtualizer` so a ~5.9K-index × 32-node grid renders smoothly.

function GridMode({ grid, filter, nodeFilter, onSelectShard }: {
  grid: ShardMapGrid; filter: string
  nodeFilter: "all" | "hot" | "warm"
  onSelectShard: (shard: SelectedShard) => void
}) {
  const dataNodes = useMemo(
    () =>
      grid.data_nodes.filter((n) => {
        if (nodeFilter === "hot") return n.tier === "hot"
        if (nodeFilter === "warm") return n.tier === "warm"
        return true
      }),
    [grid.data_nodes, nodeFilter],
  )

  const rows = useMemo(() => {
    const f = filter.toLowerCase()
    return f ? grid.indices.filter((i) => i.index.toLowerCase().includes(f)) : grid.indices
  }, [grid.indices, filter])

  const scrollRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => GRID_ROW_HEIGHT,
    overscan: 12,
  })

  const totalWidth = INDEX_COL_WIDTH + dataNodes.length * NODE_COL_WIDTH

  return (
    <div ref={scrollRef} className="flex-1 overflow-auto h-full">
      <div style={{ minWidth: `${totalWidth}px` }}>
        {/* Sticky header row */}
        <div className="sticky top-0 z-10 flex bg-eo-bg border-b border-eo-border text-[10px] font-mono">
          <div
            className="sticky left-0 z-20 bg-eo-bg border-r border-eo-border py-1 px-2 flex items-center justify-between shrink-0"
            style={{ width: INDEX_COL_WIDTH }}
          >
            <span className="text-eo-muted uppercase">Index</span>
            <span className="text-eo-muted uppercase">Size</span>
          </div>
          {dataNodes.map((node) => (
            <div
              key={node.name}
              className="text-center py-1 px-1 border-r border-eo-border shrink-0"
              style={{ width: NODE_COL_WIDTH }}
            >
              <div className="text-eo-stone truncate" title={node.name}>{node.short}</div>
              <div className="h-1 bg-eo-border rounded-full mt-0.5 mx-1 overflow-hidden">
                <div className={cn("h-full rounded-full", diskColor(node.disk_used_percent))} style={{ width: `${node.disk_used_percent}%` }} />
              </div>
            </div>
          ))}
        </div>

        {/* Virtualized body */}
        <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: "relative" }}>
          {rowVirtualizer.getVirtualItems().map((vRow) => {
            const idx = rows[vRow.index]
            return (
              <div
                key={idx.index}
                className="group flex border-t border-eo-border/20 hover:bg-eo-surface/30 text-[10px] font-mono absolute left-0 w-full"
                style={{ height: `${vRow.size}px`, transform: `translateY(${vRow.start}px)` }}
              >
                <div
                  className="sticky left-0 z-10 bg-eo-bg border-r border-eo-border group-hover:bg-eo-surface/30 py-1 px-2 flex items-center justify-between gap-2 shrink-0"
                  style={{ width: INDEX_COL_WIDTH }}
                >
                  <span className="text-eo-cream truncate">{idx.index}</span>
                  <span className="text-eo-stone shrink-0">{formatBytes(idx.pri_store_size)}</span>
                </div>
                {dataNodes.map((node) => {
                  const cellShards = grid.cells[`${idx.index} ${node.name}`] ?? []
                  return (
                    <div
                      key={node.name}
                      className="text-center py-1 px-1 border-r border-eo-border/30 shrink-0"
                      style={{ width: NODE_COL_WIDTH }}
                    >
                      <div className="flex flex-wrap justify-center gap-[2px]">
                        {cellShards.map((s: ShardCell, i: number) => (
                          <button
                            key={i}
                            onClick={() => onSelectShard({
                              index: idx.index,
                              shard: s.shard,
                              prirep: s.prirep,
                              node: node.name,
                              state: s.state,
                              store: s.store,
                              docs: s.docs,
                              segments_count: s.segments_count,
                            })}
                            className={cn(
                              "w-[10px] h-[10px] rounded-sm cursor-pointer hover:ring-1 hover:ring-eo-amber transition-shadow",
                              s.prirep === "p" ? "bg-eo-amber" : "border border-eo-cream/60",
                            )}
                            title={`${idx.index}[${s.shard}] ${s.prirep === "p" ? "primary" : "replica"} ${formatBytes(s.store)}`}
                          />
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/* ============ Pivot Mode ============ */
//
// Consumes the precomputed dynamic-depth `pivot` snapshot tree directly. Each node already carries
// its rollup (`total_size`, `shard_count`, `index_count`) and per-data-node aggregates (`per_node`),
// so there is no client-side aggregation — only expand/collapse state, a text filter, and the
// heatmap color formula remain. Rendered recursively: the hierarchy label and its heatmap row share
// one flex row so the columns stay aligned with the sticky node header.

function nodeMatchesFilter(node: PivotNode, f: string): boolean {
  if (!f) return true
  if (node.key.toLowerCase().includes(f)) return true
  return node.children.some((c) => nodeMatchesFilter(c, f))
}

function PivotMode({ tree, filter }: { tree: PivotTree; filter: string }) {
  const f = filter.toLowerCase()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const roots = useMemo(
    () => (f ? tree.roots.filter((r) => nodeMatchesFilter(r, f)) : tree.roots),
    [tree.roots, f],
  )

  const columns = tree.data_nodes
  const totalWidth = 340 + columns.length * NODE_COL_WIDTH

  return (
    <div className="flex-1 overflow-auto h-full">
      <div style={{ minWidth: `${totalWidth}px` }}>
        {/* Sticky node-column header */}
        <div className="sticky top-0 z-10 flex bg-eo-bg border-b border-eo-border text-[10px] font-mono">
          <div className="sticky left-0 z-20 bg-eo-bg border-r border-eo-border shrink-0" style={{ width: 340 }} />
          {columns.map((node) => (
            <div key={node.name} className="text-center py-1 px-2 shrink-0" style={{ width: NODE_COL_WIDTH }}>
              <div className="text-eo-stone truncate" title={node.name}>{node.short}</div>
              <div className="text-[9px] text-eo-muted">{formatPercent(node.disk_used_percent)}</div>
              <div className="h-1 bg-eo-border rounded-full mt-0.5 overflow-hidden">
                <div className={cn("h-full rounded-full", diskColor(node.disk_used_percent))} style={{ width: `${node.disk_used_percent}%` }} />
              </div>
            </div>
          ))}
        </div>

        {/* Recursive tree body */}
        <div>
          {roots.map((root) => (
            <PivotRow
              key={root.key}
              node={root}
              columns={columns}
              maxCellSize={tree.max_cell_size}
              expanded={expanded}
              toggle={toggle}
              filter={f}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function PivotRow({ node, columns, maxCellSize, expanded, toggle, filter }: {
  node: PivotNode
  columns: PivotTree["data_nodes"]
  maxCellSize: number
  expanded: Set<string>
  toggle: (key: string) => void
  filter: string
}) {
  const isExpanded = expanded.has(node.key)
  const hasChildren = node.children.length > 0
  const perNode = useMemo(() => {
    const map = new Map<string, { shard_count: number; size: number }>()
    for (const agg of node.per_node) map.set(agg.node, agg)
    return map
  }, [node.per_node])

  const visibleChildren = filter
    ? node.children.filter((c) => nodeMatchesFilter(c, filter))
    : node.children

  return (
    <>
      <div className="flex border-t border-eo-border/20 hover:bg-eo-surface/20 text-[10px] font-mono">
        {/* Hierarchy label (sticky left) */}
        <button
          onClick={() => hasChildren && toggle(node.key)}
          className={cn(
            "sticky left-0 z-10 bg-eo-bg flex items-center gap-2 py-1 pr-3 border-r border-eo-border text-left shrink-0",
            hasChildren ? "hover:bg-eo-surface/50 cursor-pointer" : "cursor-default",
          )}
          style={{ width: 340, paddingLeft: `${8 + node.depth * 16}px` }}
        >
          {hasChildren ? (
            <span className="material-symbols-outlined text-[14px] text-eo-muted">
              {isExpanded ? "expand_more" : "chevron_right"}
            </span>
          ) : (
            <span className="w-[14px] shrink-0" />
          )}
          <span className={cn("truncate flex-1", node.depth === 0 ? "font-bold text-eo-amber" : "text-eo-cream")}>
            {node.label}
          </span>
          <span className="text-eo-stone text-[10px] shrink-0">{node.index_count}</span>
          <span className="text-eo-muted text-[10px] shrink-0">{formatBytes(node.total_size)}</span>
        </button>

        {/* Per-node heatmap cells */}
        {columns.map((col) => {
          const agg = perNode.get(col.name)
          const size = agg?.size ?? 0
          const intensity = maxCellSize > 0 ? size / maxCellSize : 0
          return (
            <div key={col.name} className="text-center py-0.5 px-2 shrink-0" style={{ width: NODE_COL_WIDTH }}>
              {size > 0 && (
                <div
                  className="rounded-sm mx-auto h-4 flex items-center justify-center text-[9px]"
                  style={{ backgroundColor: `rgba(212, 165, 116, ${Math.max(0.08, intensity * 0.6)})` }}
                  title={`${node.key} on ${col.name}: ${agg?.shard_count ?? 0} shards, ${formatBytes(size)}`}
                >
                  <span className="text-eo-cream/80">{formatBytes(size)}</span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Children */}
      {isExpanded &&
        visibleChildren.map((child) => (
          <PivotRow
            key={child.key}
            node={child}
            columns={columns}
            maxCellSize={maxCellSize}
            expanded={expanded}
            toggle={toggle}
            filter={filter}
          />
        ))}
    </>
  )
}
