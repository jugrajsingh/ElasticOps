import { useState, useMemo } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useAnalysis, useShards, type ShardInfo } from "@/api/es"
import { formatBytes, formatNumber, healthColor } from "@/lib/format"
import { cn } from "@/lib/utils"

const SEVERITY_STYLES: Record<string, string> = {
  high: "bg-eo-brick/20 text-eo-brick border-eo-brick",
  medium: "bg-eo-terracotta/20 text-eo-terracotta border-eo-terracotta",
  low: "bg-eo-muted/20 text-eo-stone border-eo-muted",
}

const SEVERITY_BORDER_COLORS: Record<string, string> = {
  high: "#B8706E",
  medium: "#CC8B65",
  low: "#78716C",
}

const OPP_TYPE_LABELS: Record<string, string> = {
  "over-sharded": "Over-sharded",
  "under-sharded": "Under-sharded",
  "segment-fragmentation": "Segment Fragmentation",
  "deleted-docs": "Deleted Docs",
  "shard-imbalance": "Shard Imbalance",
}

type SortKey = "name" | "pri" | "rep" | "docs" | "size" | "avgShard" | "maxSeg" | "issues"
type SortDir = "asc" | "desc"

function SortHeader({ label, sortKey: key, current, dir, onSort, align }: {
  label: string; sortKey: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void; align?: "right"
}) {
  const active = current === key
  return (
    <th className={cn("py-2 px-2 cursor-pointer select-none hover:text-eo-cream transition-colors", align === "right" && "text-right")} onClick={() => onSort(key)}>
      {label}{active && <span className="ml-1 text-eo-amber">{dir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </th>
  )
}

export default function Indices() {
  const { activeCluster } = useClusterContext()
  const [problemsOnly, setProblemsOnly] = useState(false)
  const { data: analysis } = useAnalysis(activeCluster?.id ?? null, problemsOnly)
  const { data: shards } = useShards(activeCluster?.id ?? null)
  const [selectedIndex, setSelectedIndex] = useState<string | null>(null)
  const [filter, setFilter] = useState("")
  const [showSystem, setShowSystem] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>("name")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "name" ? "asc" : "desc")
    }
  }

  const shardsByIndex = useMemo(() => {
    if (!shards) return new Map<string, ShardInfo[]>()
    const map = new Map<string, ShardInfo[]>()
    for (const s of shards) {
      const list = map.get(s.index) ?? []
      list.push(s)
      map.set(s.index, list)
    }
    return map
  }, [shards])

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }
  if (!analysis) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Analyzing indices...</div>
  }

  const indices = analysis.indices
  const filteredIndices = indices.filter((idx) => {
    if (!showSystem && idx.name.startsWith(".")) return false
    if (filter && !idx.name.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  const sortedIndices = [...filteredIndices].sort((a, b) => {
    let cmp = 0
    switch (sortKey) {
      case "name": cmp = a.name.localeCompare(b.name); break
      case "pri": cmp = a.pri_count - b.pri_count; break
      case "rep": cmp = a.rep_count - b.rep_count; break
      case "docs": cmp = a.doc_count - b.doc_count; break
      case "size": cmp = a.pri_store_bytes - b.pri_store_bytes; break
      case "avgShard": cmp = a.avg_shard_size_gb - b.avg_shard_size_gb; break
      case "maxSeg": cmp = a.max_segments_per_shard - b.max_segments_per_shard; break
      case "issues": cmp = a.opportunity_count - b.opportunity_count; break
    }
    return sortDir === "asc" ? cmp : -cmp
  })

  const totalShards = indices.reduce((sum, i) => sum + i.pri_count * (1 + i.rep_count), 0)
  const totalSize = indices.reduce((sum, i) => sum + i.pri_store_bytes, 0)

  const selectedData = indices.find((i) => i.name === selectedIndex)
  const selectedShards = shardsByIndex.get(selectedIndex ?? "") ?? []

  return (
    <div className="flex h-full">
      {/* Left: Index table */}
      <div className={cn("flex-1 flex flex-col min-w-0", selectedIndex ? "w-[70%]" : "w-full")}>
        <div className="p-4 border-b border-eo-border space-y-3">
          {/* Filter bar */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Filter indices..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-64 bg-eo-bg border border-eo-border rounded px-3 py-1.5 text-sm font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            />
            <button
              onClick={() => setShowSystem(!showSystem)}
              className={cn(
                "px-3 py-1.5 rounded text-xs font-mono border transition-colors",
                showSystem ? "border-eo-amber text-eo-amber bg-eo-amber/10" : "border-eo-border text-eo-muted hover:text-eo-stone",
              )}
            >System</button>
            <button
              onClick={() => setProblemsOnly(!problemsOnly)}
              className={cn(
                "px-3 py-1.5 rounded text-xs font-mono border transition-colors",
                problemsOnly ? "border-eo-brick text-eo-brick bg-eo-brick/10" : "border-eo-border text-eo-muted hover:text-eo-stone",
              )}
            >Problems only</button>
          </div>

          {/* Stats row */}
          <div className="flex items-center gap-6 text-xs font-mono text-eo-stone">
            <span>{analysis.total_indices} indices</span>
            <span>{formatNumber(totalShards)} shards</span>
            <span>{formatBytes(totalSize)} primary</span>
            {analysis.total_wasted_shards > 0 && (
              <span className="text-eo-brick">{formatNumber(analysis.total_wasted_shards)} wasted shards</span>
            )}
            {analysis.total_with_opportunities > 0 && (
              <span className="text-eo-terracotta">{analysis.total_with_opportunities} with issues</span>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-xs font-mono">
            <thead className="text-eo-muted text-left uppercase tracking-wider sticky top-0 bg-eo-bg">
              <tr className="border-b border-eo-border">
                <th className="py-2 px-2 w-4">H</th>
                <SortHeader label="Index" sortKey="name" current={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Pri" sortKey="pri" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Rep" sortKey="rep" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Docs" sortKey="docs" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Pri Size" sortKey="size" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Avg Shard" sortKey="avgShard" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Max Seg" sortKey="maxSeg" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Issues" sortKey="issues" current={sortKey} dir={sortDir} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody className="text-eo-cream">
              {sortedIndices.map((idx) => (
                <tr
                  key={idx.name}
                  onClick={() => setSelectedIndex(idx.name === selectedIndex ? null : idx.name)}
                  className={cn(
                    "border-b border-eo-border/30 cursor-pointer transition-colors",
                    idx.name === selectedIndex
                      ? "bg-eo-amber/10 border-l-4 border-l-eo-amber"
                      : "hover:bg-eo-surface/50 border-l-4 border-l-transparent",
                  )}
                >
                  <td className="py-1.5 px-2"><span className={cn("w-2 h-2 rounded-full inline-block", healthColor(idx.health))} /></td>
                  <td className="py-1.5 px-2 truncate max-w-[300px]">{idx.name}</td>
                  <td className="py-1.5 px-2 text-right">{idx.pri_count}</td>
                  <td className="py-1.5 px-2 text-right">{idx.rep_count}</td>
                  <td className="py-1.5 px-2 text-right">{formatNumber(idx.doc_count)}</td>
                  <td className="py-1.5 px-2 text-right">{formatBytes(idx.pri_store_bytes)}</td>
                  <td className="py-1.5 px-2 text-right text-eo-stone">{idx.avg_shard_size_gb.toFixed(1)}GB</td>
                  <td className="py-1.5 px-2 text-right text-eo-stone">{idx.max_segments_per_shard}</td>
                  <td className="py-1.5 px-2">
                    <div className="flex gap-1 flex-wrap">
                      {idx.opportunities.map((opp, i) => (
                        <span key={i} className={cn("px-1.5 py-0.5 rounded text-[10px] border", SEVERITY_STYLES[opp.severity] ?? SEVERITY_STYLES.low)}>
                          {OPP_TYPE_LABELS[opp.type] ?? opp.type}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: Detail panel */}
      {selectedData && (
        <div className="w-[30%] min-w-[350px] border-l border-eo-border bg-eo-surface overflow-y-auto">
          <div className="p-4 space-y-4">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className={cn("w-2.5 h-2.5 rounded-full", healthColor(selectedData.health))} />
                  <h2 className="text-sm font-semibold text-eo-cream truncate">{selectedData.name}</h2>
                </div>
                <div className="text-xs text-eo-stone font-mono mt-1">{selectedData.status}</div>
              </div>
              <button onClick={() => setSelectedIndex(null)} className="text-eo-muted hover:text-eo-cream">
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>

            {/* Metrics */}
            <div className="grid grid-cols-3 gap-2">
              <MiniMetric label="Docs" value={formatNumber(selectedData.doc_count)} />
              <MiniMetric label="Size" value={formatBytes(selectedData.pri_store_bytes)} />
              <MiniMetric label="Replicas" value={selectedData.rep_count.toString()} />
            </div>

            {/* Opportunities */}
            {selectedData.opportunities.length > 0 && (
              <div>
                <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono mb-2">Opportunities</h3>
                <div className="space-y-2">
                  {selectedData.opportunities.map((opp, i) => (
                    <div
                      key={i}
                      className="border-l-2 pl-3 py-2 bg-eo-bg rounded-r"
                      style={{ borderLeftColor: SEVERITY_BORDER_COLORS[opp.severity] ?? SEVERITY_BORDER_COLORS.low }}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] border", SEVERITY_STYLES[opp.severity] ?? SEVERITY_STYLES.low)}>
                          {opp.severity}
                        </span>
                        <span className="text-xs font-semibold text-eo-cream">{OPP_TYPE_LABELS[opp.type] ?? opp.type}</span>
                      </div>
                      <p className="text-xs text-eo-stone">{opp.detail}</p>
                      <div className="mt-1.5 px-2 py-1 rounded bg-eo-amber/5 text-[11px] text-eo-amber/70">
                        <span className="font-semibold">Recommendation:</span>{" "}
                        {opp.type === "over-sharded" && `Reindex with ${opp.target_shards} shards`}
                        {opp.type === "under-sharded" && `Reindex with ${opp.target_shards} shards`}
                        {opp.type === "segment-fragmentation" && "Force merge to 1 segment per shard"}
                        {opp.type === "shard-imbalance" && "Informational — no action needed"}
                        {opp.type === "deleted-docs" && "Force merge to reclaim disk space"}
                      </div>
                      {opp.wasted_shards > 0 && (
                        <p className="text-[10px] text-eo-brick mt-1">{opp.wasted_shards} wasted shards</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2">
              {selectedData.opportunities.some((opp) => opp.type === "segment-fragmentation") && (
                <button className="px-3 py-1.5 rounded text-xs font-mono border border-eo-amber text-eo-amber hover:bg-eo-amber/10 transition-colors">
                  Force Merge
                </button>
              )}
              <button className="px-3 py-1.5 rounded text-xs font-mono bg-eo-amber text-eo-bg hover:bg-eo-amber/90 transition-colors">
                Add to Queue
              </button>
            </div>

            {/* Shard distribution */}
            <div>
              <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono mb-2">Shard Distribution</h3>
              <table className="w-full text-xs font-mono">
                <thead className="text-eo-muted">
                  <tr>
                    <th className="text-left py-1">#</th>
                    <th className="text-center py-1">P/R</th>
                    <th className="text-right py-1">Size</th>
                    <th className="text-right py-1">Segs</th>
                    <th className="text-right py-1">Docs</th>
                    <th className="text-left py-1 pl-2">Node</th>
                  </tr>
                </thead>
                <tbody className="text-eo-cream">
                  {selectedShards
                    .sort((a, b) => a.shard - b.shard || (a.prirep === "p" ? -1 : 1))
                    .map((s, i) => (
                      <tr key={`${s.shard}-${s.prirep}-${i}`} className="border-t border-eo-border/30">
                        <td className="py-1">{s.shard}</td>
                        <td className="py-1 text-center">
                          <span className={cn("px-1 rounded text-[10px]",
                            s.prirep === "p" ? "bg-eo-amber/20 text-eo-amber" : "bg-eo-muted/20 text-eo-stone"
                          )}>{s.prirep === "p" ? "P" : "R"}</span>
                        </td>
                        <td className="py-1 text-right">{formatBytes(s.store)}</td>
                        <td className={cn("py-1 text-right",
                          s.segments_count > 30 ? "text-eo-brick font-semibold" : s.segments_count > 10 ? "text-eo-terracotta" : ""
                        )}>{s.segments_count}</td>
                        <td className="py-1 text-right">{formatNumber(s.docs)}</td>
                        <td className="py-1 pl-2 truncate max-w-[100px] text-eo-stone">{s.node ?? "-"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-eo-bg rounded p-2">
      <div className="text-[10px] text-eo-muted font-mono uppercase">{label}</div>
      <div className="text-sm font-semibold font-mono text-eo-cream">{value}</div>
    </div>
  )
}
