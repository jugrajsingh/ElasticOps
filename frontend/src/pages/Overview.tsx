import { useClusterContext } from "@/context/ClusterContext"
import { useOverview } from "@/api/es"
import { formatBytes, formatNumber, diskColor, diskTextColor } from "@/lib/format"
import { cn } from "@/lib/utils"

const STORAGE_COLORS = [
  "bg-eo-amber",
  "bg-eo-sage",
  "bg-[#C4918E]",
  "bg-[#B8835A]",
  "bg-[#6B9B9B]",
  "bg-eo-terracotta",
  "bg-eo-brick",
  "bg-[#8B7EC8]",
  "bg-[#5DADE2]",
  "bg-[#A9CCB4]",
  "bg-eo-muted",
]

const STORAGE_DOT_COLORS = [
  "bg-eo-amber",
  "bg-eo-sage",
  "bg-[#C4918E]",
  "bg-[#B8835A]",
  "bg-[#6B9B9B]",
  "bg-eo-terracotta",
  "bg-eo-brick",
  "bg-[#8B7EC8]",
  "bg-[#5DADE2]",
  "bg-[#A9CCB4]",
  "bg-eo-muted",
]

export default function Overview() {
  const { activeCluster } = useClusterContext()
  const { data, isLoading } = useOverview(activeCluster?.id ?? null)

  if (!activeCluster) {
    return (
      <div className="flex items-center justify-center h-full text-eo-stone">
        Select a cluster to view overview
      </div>
    )
  }

  if (isLoading || !data) {
    return (
      <div className="flex items-center justify-center h-full text-eo-stone">
        Loading cluster data...
      </div>
    )
  }

  const h = data.health
  const totalStorage = data.nodes.reduce((sum, n) => sum + n.disk_total, 0)
  const usedStorage = data.nodes.reduce((sum, n) => sum + n.disk_used, 0)
  const rc = data.node_role_counts

  const roleBreakdown = [
    rc.master > 0 ? `mstr:${rc.master}` : null,
    rc.data > 0 ? `data:${rc.data}` : null,
    rc.coord > 0 ? `coord:${rc.coord}` : null,
    rc.ingest > 0 ? `ingest:${rc.ingest}` : null,
    rc.other > 0 ? `other:${rc.other}` : null,
  ].filter(Boolean).join(" ")

  const sortedNodes = [...data.nodes].sort((a, b) => b.disk_used_percent - a.disk_used_percent)
  const midpoint = Math.ceil(sortedNodes.length / 2)
  const col1Nodes = sortedNodes.slice(0, midpoint)
  const col2Nodes = sortedNodes.slice(midpoint)

  const totalBreakdownBytes = data.storage_breakdown.reduce((s, g) => s + g.size_bytes, 0)

  return (
    <div className="p-4 flex flex-col gap-4 overflow-hidden h-full">
      {/* ROW 1: Metric Cards */}
      <div className="grid grid-cols-6 gap-3 shrink-0">
        <MetricCard label="Nodes" value={h.number_of_nodes} sub={roleBreakdown} />
        <MetricCard label="Indices" value={formatNumber(data.index_count)} />
        <MetricCard label="Shards" value={formatNumber(h.active_shards)} sub={`pri: ${formatNumber(h.active_primary_shards)}`} />
        <MetricCard label="Storage" value={formatBytes(usedStorage)} sub={`of ${formatBytes(totalStorage)}`} />
        <MetricCard
          label="Relocating"
          value={h.relocating_shards}
          accent={h.relocating_shards > 0 ? "text-eo-terracotta" : undefined}
        />
        <MetricCard
          label="Unassigned"
          value={h.unassigned_shards}
          accent={h.unassigned_shards > 0 ? "text-eo-brick" : "text-eo-sage"}
        />
      </div>

      {/* ROW 2: Node Disk Utilization */}
      <div className="flex-1 min-h-0 bg-eo-surface border border-eo-border rounded p-4 flex flex-col">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xs font-bold uppercase tracking-widest text-eo-muted">Node Disk Utilization</h3>
          <div className="flex gap-4 text-[9px] font-bold uppercase">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eo-sage" />
              <span>Healthy</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eo-terracotta" />
              <span>Warning</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eo-brick" />
              <span>Critical</span>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-12 overflow-y-auto custom-scrollbar pr-2 flex-1 min-h-0">
          <div className="flex flex-col gap-1.5">
            {col1Nodes.map((node) => (
              <NodeDiskBar key={node.name} name={node.name} percent={node.disk_used_percent} />
            ))}
          </div>
          <div className="flex flex-col gap-1.5">
            {col2Nodes.map((node) => (
              <NodeDiskBar key={node.name} name={node.name} percent={node.disk_used_percent} />
            ))}
          </div>
        </div>
      </div>

      {/* ROW 3: Cluster Storage Breakdown */}
      {data.storage_breakdown.length > 0 && (
        <div className="shrink-0 bg-eo-surface border border-eo-border rounded p-4">
          <h3 className="text-xs font-bold uppercase tracking-widest text-eo-muted mb-3">Cluster Storage Breakdown</h3>
          <div className="flex h-5 w-full rounded overflow-hidden">
            {data.storage_breakdown.map((group, i) => {
              const pct = totalBreakdownBytes > 0 ? (group.size_bytes / totalBreakdownBytes) * 100 : 0
              return (
                <div
                  key={group.name}
                  className={cn("h-full", STORAGE_COLORS[i % STORAGE_COLORS.length])}
                  style={{ width: `${pct}%` }}
                  title={`${group.name}: ${formatBytes(group.size_bytes)}`}
                />
              )
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-[10px] font-mono">
            {data.storage_breakdown.map((group, i) => (
              <div key={group.name} className="flex items-center gap-2">
                <span className={cn("w-2 h-2 rounded", STORAGE_DOT_COLORS[i % STORAGE_DOT_COLORS.length])} />
                <span className="text-eo-cream capitalize">{group.name}</span>
                <span className="text-eo-stone">{formatBytes(group.size_bytes)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ROW 4: Active Shard Movements */}
      <div className="shrink-0 bg-eo-surface border border-eo-border rounded p-4">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-xs font-bold uppercase tracking-widest text-eo-muted">Active Shard Movements</h3>
          {data.recoveries.length > 0 && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-eo-terracotta/20 text-eo-terracotta uppercase">
              {data.recoveries.length} Active
            </span>
          )}
        </div>
        <table className="w-full text-left font-mono text-[11px]">
          <thead>
            <tr className="text-eo-muted border-b border-eo-border">
              <th className="pb-2 font-normal">Index</th>
              <th className="pb-2 font-normal">Shard</th>
              <th className="pb-2 font-normal">From &rarr; To</th>
              <th className="pb-2 font-normal w-48">Progress</th>
              <th className="pb-2 font-normal text-right">Speed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-eo-border/50">
            {data.recoveries.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-4 text-center text-eo-muted text-xs">
                  No active movements
                </td>
              </tr>
            ) : (
              data.recoveries.map((r, i) => {
                const pct = r.bytes_total > 0 ? Math.round((r.bytes_recovered / r.bytes_total) * 100) : 0
                return (
                  <tr key={`${r.index}-${r.shard}-${i}`}>
                    <td className="py-2.5 text-eo-cream">{r.index}</td>
                    <td className="py-2.5 text-eo-stone">[{r.shard}]</td>
                    <td className="py-2.5 text-eo-stone">
                      {r.source_node} <span className="text-eo-amber">&rarr;</span> {r.target_node}
                    </td>
                    <td className="py-2.5">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 bg-eo-muted/30 h-1.5 rounded-full overflow-hidden">
                          <div className="bg-eo-amber h-full" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-[10px] w-6">{pct}%</span>
                      </div>
                    </td>
                    <td className="py-2.5 text-right text-eo-stone">{r.bytes_percent}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NodeDiskBar({ name, percent }: { name: string; percent: number }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[11px]">
      <span className="w-[120px] text-eo-stone text-right shrink-0">{name}</span>
      <div className="flex-1 bg-eo-bg h-2.5 rounded-sm overflow-hidden">
        <div
          className={cn("h-full rounded-sm", diskColor(percent))}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <span className={cn("w-10 text-right shrink-0", diskTextColor(percent))}>
        {Math.round(percent)}%
      </span>
    </div>
  )
}

function MetricCard({ label, value, sub, accent }: {
  label: string
  value: string | number
  sub?: string
  accent?: string
}) {
  return (
    <div className="bg-eo-surface border border-eo-border p-3 rounded">
      <p className="text-[10px] text-eo-muted uppercase font-bold tracking-wider mb-1">{label}</p>
      <div className="flex items-baseline gap-2">
        <span className={cn("text-2xl font-bold font-mono", accent ?? "text-eo-cream")}>{value}</span>
        {sub && <span className="text-[9px] font-mono text-eo-muted">{sub}</span>}
      </div>
    </div>
  )
}
