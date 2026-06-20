import { useState, useMemo } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useShardMap, useClusterHealth, type NodeInfo, type ShardInfo, type IndexInfo } from "@/api/es"
import { formatBytes, formatNumber, formatPercent, diskColor } from "@/lib/format"
import { cn } from "@/lib/utils"

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

export default function ShardMap() {
  const { activeCluster } = useClusterContext()
  const { data } = useShardMap(activeCluster?.id ?? null)
  const { data: health } = useClusterHealth(activeCluster?.id ?? null)
  const [mode, setMode] = useState<Mode>("grid")
  const [filter, setFilter] = useState("")
  const [nodeFilter, setNodeFilter] = useState<"all" | "hot" | "warm">("all")
  const [selectedShard, setSelectedShard] = useState<SelectedShard | null>(null)

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }
  if (!data) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Loading shard map...</div>
  }

  const dataNodes = data.nodes.filter((n) => n.role.includes("d")).sort((a, b) => a.name.localeCompare(b.name))
  const clusterStatus = health?.status?.toUpperCase() ?? "UNKNOWN"

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
            <GridMode nodes={data.nodes} indices={data.indices} shards={data.shards} filter={filter} nodeFilter={nodeFilter} onSelectShard={setSelectedShard} />
          ) : (
            <PivotMode nodes={data.nodes} indices={data.indices} shards={data.shards} filter={filter} />
          )}
        </div>

        {/* Shard detail panel */}
        {selectedShard && (
          <ShardDetailPanel shard={selectedShard} dataNodes={dataNodes} onClose={() => setSelectedShard(null)} />
        )}
      </div>

      {/* Footer status bar */}
      <div className="h-8 flex items-center px-4 border-t border-eo-border bg-eo-surface/50 text-[10px] font-mono text-eo-muted gap-4">
        <span>{mode === "grid" ? "Grid Mode" : "Pivot Mode"}</span>
        <span>&middot;</span>
        <span>{data.indices.length} indices</span>
        <span>&middot;</span>
        <span>{data.shards.length} shards</span>
        <span>&middot;</span>
        <span>CLUSTER: {clusterStatus}</span>
      </div>
    </div>
  )
}

/* ============ Shard Detail Panel ============ */

function ShardDetailPanel({ shard, dataNodes, onClose }: {
  shard: SelectedShard; dataNodes: NodeInfo[]; onClose: () => void
}) {
  const otherNodes = dataNodes.filter((n) => n.name !== shard.node)

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
          <MetricRow label="Docs" value={formatNumber(shard.docs)} />
          <MetricRow label="Segments" value={String(shard.segments_count)} highlight={shard.segments_count > 10} />
        </div>

        {/* Actions */}
        <h3 className="text-xs font-mono text-eo-muted uppercase mt-6 mb-3">Actions</h3>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] font-mono text-eo-stone block mb-1">Relocate to...</label>
            <select
              className="w-full bg-eo-surface border border-eo-border rounded px-2 py-1.5 text-xs font-mono text-eo-cream focus:border-eo-amber focus:outline-none"
              defaultValue=""
            >
              <option value="" disabled>Select target node</option>
              {otherNodes.map((n) => (
                <option key={n.name} value={n.name}>{n.name}</option>
              ))}
            </select>
          </div>
          <button
            className="w-full px-3 py-1.5 text-xs font-mono bg-eo-amber/20 text-eo-amber border border-eo-amber/40 rounded hover:bg-eo-amber/30 transition-colors cursor-not-allowed opacity-60"
            disabled
          >
            Relocate Shard (coming soon)
          </button>
        </div>
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

function shortenNodeName(name: string): string {
  const segments = name.split("-")
  if (segments.length <= 2) return name
  return segments.slice(-2).join("-")
}

function GridMode({ nodes, indices, shards, filter, nodeFilter, onSelectShard }: {
  nodes: NodeInfo[]; indices: IndexInfo[]; shards: ShardInfo[]; filter: string
  nodeFilter: "all" | "hot" | "warm"
  onSelectShard: (shard: SelectedShard) => void
}) {
  const allDataNodes = nodes.filter((n) => n.role.includes("d")).sort((a, b) => a.name.localeCompare(b.name))
  const dataNodes = allDataNodes.filter((n) => {
    if (nodeFilter === "hot") return n.role.includes("h")
    if (nodeFilter === "warm") return n.role.includes("w")
    return true
  })
  const filteredIndices = indices
    .filter((i) => !i.index.startsWith(".") && (!filter || i.index.toLowerCase().includes(filter.toLowerCase())))
    .sort((a, b) => b.pri_store_size - a.pri_store_size)

  // Build shard lookup: index -> node -> ShardInfo[]
  const shardLookup = useMemo(() => {
    const map = new Map<string, Map<string, ShardInfo[]>>()
    for (const s of shards) {
      if (!s.node) continue
      if (!map.has(s.index)) map.set(s.index, new Map())
      const nodeMap = map.get(s.index)!
      if (!nodeMap.has(s.node)) nodeMap.set(s.node, [])
      nodeMap.get(s.node)!.push(s)
    }
    return map
  }, [shards])

  return (
    <div className="flex-1 overflow-auto h-full">
      <table className="text-[10px] font-mono" style={{ minWidth: `${280 + dataNodes.length * 100}px` }}>
        <thead className="sticky top-0 z-10 bg-eo-bg">
          <tr>
            <th className="sticky left-0 z-20 bg-eo-bg border-r border-eo-border py-1 px-2 w-[280px]">
              <div className="flex items-center justify-between">
                <span className="text-eo-muted uppercase">Index</span>
                <span className="text-eo-muted uppercase">Size</span>
              </div>
            </th>
            {dataNodes.map((node) => (
              <th key={node.name} className="text-center py-1 px-1 min-w-[100px] border-r border-eo-border">
                <div className="text-eo-stone truncate" title={node.name}>{shortenNodeName(node.name)}</div>
                <div className="h-1 bg-eo-border rounded-full mt-0.5 mx-1 overflow-hidden">
                  <div className={cn("h-full rounded-full", diskColor(node.disk_used_percent))} style={{ width: `${node.disk_used_percent}%` }} />
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filteredIndices.map((idx) => {
            const nodeShards = shardLookup.get(idx.index)
            return (
              <tr key={idx.index} className="group border-t border-eo-border/20 hover:bg-eo-surface/30">
                <td className="sticky left-0 z-20 bg-eo-bg border-r border-eo-border group-hover:bg-eo-surface/30 py-1 px-2 w-[280px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-eo-cream truncate">{idx.index}</span>
                    <span className="text-eo-stone shrink-0">{formatBytes(idx.pri_store_size)}</span>
                  </div>
                </td>
                {dataNodes.map((node) => {
                  const cellShards = nodeShards?.get(node.name) ?? []
                  return (
                    <td key={node.name} className="text-center py-1 px-1 border-r border-eo-border/30">
                      <div className="flex flex-wrap justify-center gap-[2px]">
                        {cellShards.map((s, i) => (
                          <button
                            key={i}
                            onClick={() => onSelectShard({
                              index: s.index,
                              shard: s.shard,
                              prirep: s.prirep,
                              node: s.node ?? "",
                              state: s.state,
                              store: s.store,
                              docs: s.docs,
                              segments_count: s.segments_count,
                            })}
                            className={cn(
                              "w-[10px] h-[10px] rounded-sm cursor-pointer hover:ring-1 hover:ring-eo-amber transition-shadow",
                              s.prirep === "p" ? "bg-eo-amber" : "border border-eo-cream/60",
                            )}
                            title={`${s.index}[${s.shard}] ${s.prirep === "p" ? "primary" : "replica"} ${formatBytes(s.store)}`}
                          />
                        ))}
                      </div>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ============ Pivot Mode ============ */

interface TreeLevel1 {
  subgroup: string        // e.g. "daas_products"
  fullPrefix: string      // e.g. "crawl/daas_products"
  indices: IndexInfo[]
  totalSize: number
}

interface TreeLevel0 {
  type: string            // e.g. "crawl"
  children: TreeLevel1[]
  totalSize: number
  indexCount: number
}

function buildTree(indices: IndexInfo[], filter: string): TreeLevel0[] {
  const level0Map = new Map<string, Map<string, IndexInfo[]>>()

  for (const idx of indices) {
    if (idx.index.startsWith(".")) continue
    if (filter && !idx.index.toLowerCase().includes(filter.toLowerCase())) continue

    const segments = idx.index.split("_")
    const type = segments[0] || idx.index
    // Use first 2 segments as subgroup key; if only 1 segment, use the full name
    const subgroup = segments.length > 1 ? segments.slice(0, 2).join("_") : segments[0]

    if (!level0Map.has(type)) level0Map.set(type, new Map())
    const subMap = level0Map.get(type)!
    if (!subMap.has(subgroup)) subMap.set(subgroup, [])
    subMap.get(subgroup)!.push(idx)
  }

  const tree: TreeLevel0[] = []
  for (const [type, subMap] of level0Map.entries()) {
    const children: TreeLevel1[] = []
    let totalSize = 0
    let indexCount = 0

    for (const [subgroup, subIndices] of subMap.entries()) {
      const subSize = subIndices.reduce((sum, i) => sum + i.pri_store_size, 0)
      children.push({
        subgroup,
        fullPrefix: `${type}/${subgroup}`,
        indices: subIndices.sort((a, b) => a.index.localeCompare(b.index)),
        totalSize: subSize,
      })
      totalSize += subSize
      indexCount += subIndices.length
    }

    children.sort((a, b) => b.totalSize - a.totalSize)
    tree.push({ type, children, totalSize, indexCount })
  }

  return tree.sort((a, b) => b.totalSize - a.totalSize)
}

function PivotMode({ nodes, indices, shards, filter }: {
  nodes: NodeInfo[]; indices: IndexInfo[]; shards: ShardInfo[]; filter: string
}) {
  const dataNodes = nodes.filter((n) => n.role.includes("d")).sort((a, b) => a.name.localeCompare(b.name))

  const tree = useMemo(() => buildTree(indices, filter), [indices, filter])

  // Shard count per (index, node)
  const shardCountByCell = useMemo(() => {
    const map = new Map<string, number>()
    for (const s of shards) {
      if (!s.node) continue
      const key = `${s.index}:${s.node}`
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return map
  }, [shards])

  // Size per (index, node)
  const sizeByCell = useMemo(() => {
    const map = new Map<string, number>()
    for (const s of shards) {
      if (!s.node) continue
      const key = `${s.index}:${s.node}`
      map.set(key, (map.get(key) ?? 0) + s.store)
    }
    return map
  }, [shards])

  // expanded keys: "crawl" for level 0, "crawl/daas_products" for level 1
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Max cell size for heatmap scaling
  const maxCellSize = useMemo(() => Math.max(...Array.from(sizeByCell.values()), 1), [sizeByCell])

  // Compute aggregated size for a list of indices on a node
  const aggregateSize = (idxList: IndexInfo[], nodeName: string) =>
    idxList.reduce((sum, idx) => sum + (sizeByCell.get(`${idx.index}:${nodeName}`) ?? 0), 0)

  // Build the visible rows for the right heatmap panel in the same order as the left panel
  type HeatRow =
    | { kind: "level0-agg"; key: string; allIndices: IndexInfo[] }
    | { kind: "level1-agg"; key: string; indices: IndexInfo[] }
    | { kind: "leaf"; key: string; idx: IndexInfo }

  const heatRows = useMemo<HeatRow[]>(() => {
    const rows: HeatRow[] = []
    for (const l0 of tree) {
      const l0Expanded = expanded.has(l0.type)
      const allIndices = l0.children.flatMap((c) => c.indices)
      if (!l0Expanded) {
        rows.push({ kind: "level0-agg", key: l0.type, allIndices })
      } else {
        for (const l1 of l0.children) {
          const l1Expanded = expanded.has(l1.fullPrefix)
          if (!l1Expanded) {
            rows.push({ kind: "level1-agg", key: l1.fullPrefix, indices: l1.indices })
          } else {
            for (const idx of l1.indices) {
              rows.push({ kind: "leaf", key: idx.index, idx })
            }
          }
        }
      }
    }
    return rows
  }, [tree, expanded])

  return (
    <div className="flex flex-1 min-h-0">
      {/* Left: hierarchy */}
      <div className="w-[340px] flex-shrink-0 border-r border-eo-border overflow-y-auto sticky left-0 bg-eo-bg z-10">
        {tree.map((l0) => {
          const l0Expanded = expanded.has(l0.type)
          return (
            <div key={l0.type}>
              {/* Level 0 row */}
              <button
                onClick={() => toggle(l0.type)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-mono hover:bg-eo-surface/50 border-b border-eo-border/30"
              >
                <span className="material-symbols-outlined text-[14px] text-eo-muted">
                  {l0Expanded ? "expand_more" : "chevron_right"}
                </span>
                <span className="truncate flex-1 text-left font-bold text-eo-amber">{l0.type}</span>
                <span className="text-eo-stone text-[10px]">{l0.indexCount}</span>
                <span className="text-eo-muted text-[10px]">{formatBytes(l0.totalSize)}</span>
              </button>

              {l0Expanded && l0.children.map((l1) => {
                const l1Expanded = expanded.has(l1.fullPrefix)
                return (
                  <div key={l1.fullPrefix}>
                    {/* Level 1 row */}
                    <button
                      onClick={() => toggle(l1.fullPrefix)}
                      className="w-full flex items-center gap-2 pl-6 pr-3 py-1 text-[11px] font-mono hover:bg-eo-surface/40 border-b border-eo-border/20"
                    >
                      <span className="material-symbols-outlined text-[13px] text-eo-muted">
                        {l1Expanded ? "expand_more" : "chevron_right"}
                      </span>
                      <span className="truncate flex-1 text-left text-eo-cream">{l1.subgroup}</span>
                      <span className="text-eo-stone text-[10px]">{l1.indices.length}</span>
                      <span className="text-eo-muted text-[10px]">{formatBytes(l1.totalSize)}</span>
                    </button>

                    {l1Expanded && l1.indices.map((idx) => (
                      <div
                        key={idx.index}
                        className="flex items-center gap-2 pl-12 pr-3 py-0.5 text-[10px] font-mono text-eo-stone border-b border-eo-border/10 hover:bg-eo-surface/30"
                      >
                        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", healthColor(idx.health))} />
                        <span className="truncate flex-1">{idx.index}</span>
                        <span className="text-eo-muted">{formatBytes(idx.pri_store_size)}</span>
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>

      {/* Right: node columns with heatmap */}
      <div className="flex-1 overflow-auto">
        <table className="text-[10px] font-mono" style={{ minWidth: `${dataNodes.length * 100}px` }}>
          <thead className="sticky top-0 bg-eo-bg z-5">
            <tr>
              {dataNodes.map((node) => (
                <th key={node.name} className="text-center py-1 px-2 min-w-[100px]">
                  <div className="text-eo-stone truncate">{node.name.replace(/.*-/, "")}</div>
                  <div className="text-[9px] text-eo-muted">{formatPercent(node.disk_used_percent)}</div>
                  <div className="h-1 bg-eo-border rounded-full mt-0.5 overflow-hidden">
                    <div className={cn("h-full rounded-full", diskColor(node.disk_used_percent))} style={{ width: `${node.disk_used_percent}%` }} />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {heatRows.map((row) => {
              if (row.kind === "level0-agg") {
                return (
                  <tr key={row.key} className="border-t border-eo-border/30">
                    {dataNodes.map((node) => {
                      const totalSize = aggregateSize(row.allIndices, node.name)
                      const intensity = totalSize / maxCellSize
                      return (
                        <td key={node.name} className="text-center py-1 px-2">
                          {totalSize > 0 && (
                            <div
                              className="rounded-sm mx-auto h-5 flex items-center justify-center text-[9px]"
                              style={{ backgroundColor: `rgba(212, 165, 116, ${Math.max(0.1, intensity * 0.6)})` }}
                            >
                              <span className="text-eo-cream/80">{formatBytes(totalSize)}</span>
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              }

              if (row.kind === "level1-agg") {
                return (
                  <tr key={row.key} className="border-t border-eo-border/20">
                    {dataNodes.map((node) => {
                      const totalSize = aggregateSize(row.indices, node.name)
                      const intensity = totalSize / maxCellSize
                      return (
                        <td key={node.name} className="text-center py-0.5 px-2">
                          {totalSize > 0 && (
                            <div
                              className="rounded-sm mx-auto h-4 flex items-center justify-center text-[9px]"
                              style={{ backgroundColor: `rgba(212, 165, 116, ${Math.max(0.08, intensity * 0.5)})` }}
                            >
                              <span className="text-eo-cream/75">{formatBytes(totalSize)}</span>
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              }

              // leaf
              return (
                <tr key={row.key} className="border-t border-eo-border/10">
                  {dataNodes.map((node) => {
                    const cellSize = sizeByCell.get(`${row.idx.index}:${node.name}`) ?? 0
                    const cellCount = shardCountByCell.get(`${row.idx.index}:${node.name}`) ?? 0
                    const intensity = cellSize / maxCellSize
                    return (
                      <td key={node.name} className="text-center py-0.5 px-2">
                        {cellCount > 0 && (
                          <div
                            className="rounded-sm mx-auto h-4 flex items-center justify-center text-[9px]"
                            style={{ backgroundColor: `rgba(212, 165, 116, ${Math.max(0.05, intensity * 0.5)})` }}
                            title={`${row.idx.index} on ${node.name}: ${cellCount} shards, ${formatBytes(cellSize)}`}
                          >
                            <span className="text-eo-cream/70">{formatBytes(cellSize)}</span>
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function healthColor(status: string): string {
  switch (status) {
    case "green": return "bg-eo-sage"
    case "yellow": return "bg-eo-terracotta"
    case "red": return "bg-eo-brick"
    default: return "bg-eo-muted"
  }
}
