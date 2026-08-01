import { useEffect, useState } from "react"
import { useLocation } from "react-router-dom"
import { useClusterContext } from "@/context/ClusterContext"
import {
  useOverview,
  useUnassigned,
  useAllocationExplain,
  useRetryFailedAllocations,
  type UnassignedShard,
} from "@/api/es"
import { ApiError, getErrorMessage } from "@/api/client"
import { formatBytes, formatNumber, formatSince, diskColor, diskTextColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import QueryError from "@/components/QueryError"

export const UNASSIGNED_PANEL_ID = "unassigned-panel"

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
  const { data, isError, error, refetch } = useOverview(activeCluster?.id ?? null)
  const { data: unassigned } = useUnassigned(activeCluster?.id ?? null)
  const location = useLocation()

  // TopBar's unassigned badge links here with `#unassigned-panel`; scroll it into view on arrival.
  useEffect(() => {
    if (location.hash !== `#${UNASSIGNED_PANEL_ID}`) return
    document.getElementById(UNASSIGNED_PANEL_ID)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [location, unassigned])

  if (!activeCluster) {
    return (
      <div className="flex items-center justify-center h-full text-eo-stone">
        Select a cluster to view overview
      </div>
    )
  }

  // Snapshot-first: render as soon as a snapshot exists. Only the very first load (no snapshot yet)
  // shows a thin placeholder instead of a blocking spinner — staleness lives in the TopBar.
  if (!data) {
    if (isError) {
      return <QueryError message={getErrorMessage(error)} onRetry={refetch} />
    }
    return (
      <div className="flex items-center justify-center h-full text-eo-muted text-xs font-mono">
        Loading cluster snapshot…
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

      {/* Unassigned shards triage panel — only surfaces when the cluster actually has any. */}
      {unassigned && unassigned.length > 0 && (
        <UnassignedPanel
          clusterId={activeCluster.id}
          readOnly={!!activeCluster.read_only}
          rows={unassigned}
        />
      )}

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

function UnassignedPanel({
  clusterId,
  readOnly,
  rows,
}: {
  clusterId: number
  readOnly: boolean
  rows: UnassignedShard[]
}) {
  const [explainRow, setExplainRow] = useState<UnassignedShard | null>(null)
  const [confirmingRetry, setConfirmingRetry] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  const [retrySuccess, setRetrySuccess] = useState(false)
  const retry = useRetryFailedAllocations(clusterId)

  const handleRetry = () => {
    setRetryError(null)
    setRetrySuccess(false)
    retry.mutate(undefined, {
      onSuccess: () => {
        setConfirmingRetry(false)
        setRetrySuccess(true)
      },
      onError: (err) => {
        setConfirmingRetry(false)
        setRetryError(err instanceof ApiError ? err.detail : "Retry failed")
      },
    })
  }

  return (
    <div id={UNASSIGNED_PANEL_ID} className="shrink-0 bg-eo-surface border border-eo-brick/40 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-xs font-bold uppercase tracking-widest text-eo-brick">Unassigned Shards</h3>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-eo-brick/20 text-eo-brick uppercase">
            {rows.length}
          </span>
        </div>

        {!readOnly && (
          !confirmingRetry ? (
            <button
              onClick={() => {
                setRetryError(null)
                setRetrySuccess(false)
                setConfirmingRetry(true)
              }}
              className="px-3 py-1.5 text-xs font-mono rounded border border-eo-border text-eo-cream hover:border-eo-amber hover:text-eo-amber transition-colors"
            >
              Retry Failed Allocations
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-xs text-eo-stone font-mono">Retry failed allocations now?</span>
              <button
                onClick={handleRetry}
                disabled={retry.isPending}
                className="px-3 py-1.5 text-xs font-mono rounded bg-eo-amber/20 border border-eo-amber text-eo-amber hover:bg-eo-amber/30 transition-colors disabled:opacity-50"
              >
                {retry.isPending ? "Retrying…" : "Confirm"}
              </button>
              <button
                onClick={() => setConfirmingRetry(false)}
                disabled={retry.isPending}
                className="px-3 py-1.5 text-xs font-mono rounded border border-eo-border text-eo-stone hover:text-eo-cream transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          )
        )}
      </div>

      {retrySuccess && <div className="mb-2 text-xs text-eo-sage font-mono">Retry submitted to the cluster.</div>}
      {retryError && <div className="mb-2 text-xs text-eo-brick font-mono">{retryError}</div>}

      <div className="max-h-64 overflow-y-auto custom-scrollbar">
        <table className="w-full text-left font-mono text-[11px]">
          <thead>
            <tr className="text-eo-muted border-b border-eo-border sticky top-0 bg-eo-surface">
              <th className="pb-2 font-normal">Index</th>
              <th className="pb-2 font-normal">Shard</th>
              <th className="pb-2 font-normal">P/R</th>
              <th className="pb-2 font-normal">Reason</th>
              <th className="pb-2 font-normal">Since</th>
              <th className="pb-2 font-normal">Details</th>
              <th className="pb-2 font-normal text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-eo-border/50">
            {rows.map((row, i) => (
              <tr key={`${row.index}-${row.shard}-${row.prirep}-${i}`}>
                <td className="py-2 text-eo-cream">{row.index}</td>
                <td className="py-2 text-eo-stone">[{row.shard}]</td>
                <td className="py-2">
                  <span
                    className={cn(
                      "px-1 rounded text-[10px]",
                      row.prirep === "p" ? "bg-eo-amber/20 text-eo-amber" : "bg-eo-muted/20 text-eo-stone",
                    )}
                  >
                    {row.prirep === "p" ? "P" : "R"}
                  </span>
                </td>
                <td className="py-2 text-eo-terracotta">{row.reason ?? "-"}</td>
                <td className="py-2 text-eo-stone">{formatSince(row.at)}</td>
                <td className="py-2 text-eo-stone truncate max-w-[220px]" title={row.details ?? undefined}>
                  {row.details ?? "-"}
                </td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => setExplainRow(row)}
                    className="px-2 py-1 text-[10px] font-mono rounded border border-eo-border text-eo-stone hover:border-eo-amber hover:text-eo-amber transition-colors"
                  >
                    Explain
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {explainRow && (
        <ExplainDialog clusterId={clusterId} row={explainRow} onClose={() => setExplainRow(null)} />
      )}
    </div>
  )
}

function ExplainDialog({
  clusterId,
  row,
  onClose,
}: {
  clusterId: number
  row: UnassignedShard
  onClose: () => void
}) {
  const explain = useAllocationExplain(clusterId)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    explain.mutate(
      { index: row.index, shard: row.shard, primary: row.prirep === "p" },
      {
        onSuccess: (data) => setResult(data),
        onError: (err) => setError(err instanceof ApiError ? err.detail : "Explain failed"),
      },
    )
    // Fire exactly once per opened row — `explain` (a fresh mutation object every render) is
    // intentionally excluded from the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row])

  const explanation = typeof result?.explanation === "string" ? result.explanation : undefined
  const nodeDecisions = result?.node_allocation_decisions

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-eo-surface border border-eo-border rounded-lg w-full max-w-2xl max-h-[80vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-eo-cream">
            Allocation Explain &middot; {row.index}[{row.shard}]
          </h2>
          <button onClick={onClose} className="text-eo-muted hover:text-eo-cream">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {explain.isPending && <div className="text-xs text-eo-muted font-mono">Explaining…</div>}
        {error && <div className="text-xs text-eo-brick font-mono">{error}</div>}
        {result && (
          <div className="space-y-3">
            {explanation && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-eo-muted font-mono mb-1">
                  Explanation
                </div>
                <p className="text-xs text-eo-cream">{explanation}</p>
              </div>
            )}
            {nodeDecisions !== undefined && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-eo-muted font-mono mb-1">
                  Node Allocation Decisions
                </div>
                <pre className="text-[10px] text-eo-stone font-mono whitespace-pre-wrap bg-eo-bg rounded p-3 overflow-x-auto">
                  {JSON.stringify(nodeDecisions, null, 2)}
                </pre>
              </div>
            )}
            <details>
              <summary className="text-[10px] uppercase tracking-wider text-eo-muted font-mono cursor-pointer">
                Full response
              </summary>
              <pre className="mt-2 text-[10px] text-eo-stone font-mono whitespace-pre-wrap bg-eo-bg rounded p-3 overflow-x-auto">
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </div>
        )}
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
