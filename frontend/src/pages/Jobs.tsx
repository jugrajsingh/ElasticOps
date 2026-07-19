import { useState, useMemo } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import {
  useJobs,
  useJobSummary,
  useRecommend,
  useApproveJob,
  useRejectJob,
  useExecuteJob,
  useExecuteAll,
  useBulkApprove,
  useConcurrency,
  useClearQueue,
  useClearHistory,
  type Job,
} from "@/api/jobs"
import { getErrorMessage } from "@/api/client"
import { formatBytes, formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import QueryError from "@/components/QueryError"

type JobSortKey = "tier" | "status" | "type" | "index" | "current" | "target" | "savings" | "size"
type SortDir = "asc" | "desc"

function SortHeader({ label, sortKey: key, current, dir, onSort, align }: {
  label: string; sortKey: JobSortKey; current: JobSortKey; dir: SortDir; onSort: (k: JobSortKey) => void; align?: "right"
}) {
  const active = current === key
  return (
    <th className={cn("py-2 px-2 cursor-pointer select-none hover:text-eo-cream transition-colors", align === "right" && "text-right")} onClick={() => onSort(key)}>
      {label}{active && <span className="ml-1 text-eo-amber">{dir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </th>
  )
}

type Tab = "recommendations" | "execution"

const TIER_LABELS: Record<number, string> = { 1: "T1", 2: "T2", 3: "T3", 4: "T4" }

const DETECTORS = [
  { key: "over-sharded", label: "Over-sharded" },
  { key: "under-sharded", label: "Under-sharded" },
  { key: "segment-fragmentation", label: "Fragmentation" },
  { key: "shard-imbalance", label: "Imbalance" },
  { key: "deleted-docs", label: "Deleted docs" },
]
const STATUS_STYLES: Record<string, string> = {
  pending: "bg-eo-muted/20 text-eo-stone",
  approved: "bg-eo-amber/20 text-eo-amber",
  queued: "bg-eo-amber/10 text-eo-stone",
  executing: "bg-eo-terracotta/20 text-eo-terracotta animate-pulse-terracotta",
  completed: "bg-eo-sage/20 text-eo-sage",
  failed: "bg-eo-brick/20 text-eo-brick",
  cancelled: "bg-eo-muted/20 text-eo-muted line-through",
  rejected: "bg-eo-muted/20 text-eo-muted line-through",
}

export default function Jobs() {
  const { activeCluster } = useClusterContext()
  const [tab, setTab] = useState<Tab>("recommendations")

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }

  return (
    <div className="flex flex-col h-full">
      {/* Tab header */}
      <div className="flex items-center gap-4 px-6 border-b border-eo-border bg-eo-surface/50">
        <button
          onClick={() => setTab("recommendations")}
          className={cn("py-3 text-sm font-mono border-b-2 transition-colors",
            tab === "recommendations" ? "border-eo-amber text-eo-amber" : "border-transparent text-eo-stone hover:text-eo-cream")}
        >Suggestions</button>
        <button
          onClick={() => setTab("execution")}
          className={cn("py-3 text-sm font-mono border-b-2 transition-colors",
            tab === "execution" ? "border-eo-amber text-eo-amber" : "border-transparent text-eo-stone hover:text-eo-cream")}
        >Execution</button>
      </div>

      {tab === "recommendations" ? (
        <RecommendationsTab clusterId={activeCluster.id} />
      ) : (
        <ExecutionTab clusterId={activeCluster.id} />
      )}
    </div>
  )
}

function RecommendationsTab({ clusterId }: { clusterId: number }) {
  const { data: jobs, isError, error, refetch } = useJobs(clusterId)
  const { data: summary } = useJobSummary(clusterId)
  const recommend = useRecommend(clusterId)
  const approve = useApproveJob(clusterId)
  const reject = useRejectJob(clusterId)
  const bulkApprove = useBulkApprove(clusterId)
  const [tierFilter, setTierFilter] = useState<number | null>(null)
  const [sortKey, setSortKey] = useState<JobSortKey>("tier")
  const [sortDir, setSortDir] = useState<SortDir>("asc")
  const [selectedDetectors, setSelectedDetectors] = useState<string[]>(DETECTORS.map((d) => d.key))

  const toggleDetector = (key: string) => {
    setSelectedDetectors((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  const toggleSort = (key: JobSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "index" ? "asc" : "desc")
    }
  }

  const filtered = jobs?.filter((j) => {
    if (tierFilter !== null && j.tier !== tierFilter) return false
    return j.status === "pending" || j.status === "approved" || j.status === "rejected"
  }) ?? []

  const sortedJobs = useMemo(() => [...filtered].sort((a, b) => {
    let cmp = 0
    switch (sortKey) {
      case "tier": cmp = a.tier - b.tier; break
      case "status": cmp = a.status.localeCompare(b.status); break
      case "type": cmp = a.job_type.localeCompare(b.job_type); break
      case "index": cmp = a.index_name.localeCompare(b.index_name); break
      case "current": cmp = a.current_shards - b.current_shards; break
      case "target": cmp = a.target_shards - b.target_shards; break
      case "savings": cmp = a.estimated_savings_shards - b.estimated_savings_shards; break
      case "size": cmp = a.pri_store_bytes - b.pri_store_bytes; break
    }
    return sortDir === "asc" ? cmp : -cmp
  }), [filtered, sortKey, sortDir])

  if (!jobs && isError) {
    return <QueryError message={getErrorMessage(error)} onRetry={refetch} />
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-4">
      {/* Actions bar */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <button
            onClick={() => recommend.mutate(selectedDetectors.length === DETECTORS.length ? undefined : selectedDetectors)}
            disabled={recommend.isPending || selectedDetectors.length === 0}
            className="px-4 py-2 bg-eo-amber text-eo-bg rounded text-sm font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50"
          >
            {recommend.isPending ? "Analyzing..." : "Run Analysis"}
          </button>
          <button
            onClick={() => bulkApprove.mutate(tierFilter ?? undefined)}
            className="px-3 py-2 border border-eo-border text-eo-stone rounded text-sm font-mono hover:text-eo-cream transition-colors"
          >Approve All{tierFilter !== null ? ` T${tierFilter}` : ""}</button>

          <div className="flex gap-1 ml-4">
            <TierButton tier={null} active={tierFilter} onClick={setTierFilter} label="All" />
            {[1, 2, 3, 4].map((t) => (
              <TierButton key={t} tier={t} active={tierFilter} onClick={setTierFilter} label={`T${t}`} />
            ))}
          </div>

          {summary && (
            <div className="ml-auto flex gap-4 text-xs font-mono text-eo-stone">
              <span>{summary.total} total</span>
              <span>{summary.pending} pending</span>
              <span className="text-eo-amber">{summary.approved} approved</span>
            </div>
          )}
        </div>

        {/* Detector filter chips */}
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-eo-muted">Analyze:</span>
          <div className="flex gap-1">
            {DETECTORS.map((d) => (
              <button
                key={d.key}
                onClick={() => toggleDetector(d.key)}
                className={cn(
                  "px-2 py-1 rounded text-xs font-mono border transition-colors",
                  selectedDetectors.includes(d.key)
                    ? "border-eo-amber text-eo-amber bg-eo-amber/10"
                    : "border-eo-border text-eo-muted hover:text-eo-stone",
                )}
              >{d.label}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Job table */}
      <table className="w-full text-xs font-mono">
        <thead className="text-eo-muted text-left uppercase tracking-wider sticky top-0 bg-eo-bg">
          <tr className="border-b border-eo-border">
            <SortHeader label="T" sortKey="tier" current={sortKey} dir={sortDir} onSort={toggleSort} />
            <SortHeader label="Status" sortKey="status" current={sortKey} dir={sortDir} onSort={toggleSort} />
            <SortHeader label="Type" sortKey="type" current={sortKey} dir={sortDir} onSort={toggleSort} />
            <SortHeader label="Index" sortKey="index" current={sortKey} dir={sortDir} onSort={toggleSort} />
            <SortHeader label="Current" sortKey="current" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
            <SortHeader label="Target" sortKey="target" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
            <SortHeader label="Savings" sortKey="savings" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
            <SortHeader label="Size" sortKey="size" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
            <th className="py-2 px-2">Actions</th>
          </tr>
        </thead>
        <tbody className="text-eo-cream">
          {sortedJobs.map((job) => (
            <tr key={job.id} className="border-b border-eo-border/30 hover:bg-eo-surface/50">
              <td className="py-1.5 px-2 text-eo-amber font-semibold">{TIER_LABELS[job.tier] ?? job.tier}</td>
              <td className="py-1.5 px-2">
                <span className={cn("px-1.5 py-0.5 rounded text-[10px]", STATUS_STYLES[job.status])}>
                  {job.status}
                </span>
              </td>
              <td className="py-1.5 px-2">{job.job_type}</td>
              <td className="py-1.5 px-2 truncate max-w-[250px]">{job.index_name}</td>
              <td className="py-1.5 px-2 text-right">{job.current_shards}</td>
              <td className="py-1.5 px-2 text-right text-eo-amber">{job.target_shards}</td>
              <td className="py-1.5 px-2 text-right text-eo-sage">{job.estimated_savings_shards > 0 ? `-${job.estimated_savings_shards}` : "-"}</td>
              <td className="py-1.5 px-2 text-right">{formatBytes(job.pri_store_bytes)}</td>
              <td className="py-1.5 px-2">
                {job.status === "pending" && (
                  <div className="flex gap-1">
                    <button
                      onClick={() => approve.mutate(job.id)}
                      className="px-2 py-0.5 text-[10px] rounded border border-eo-sage text-eo-sage hover:bg-eo-sage/10"
                    >Approve</button>
                    <button
                      onClick={() => reject.mutate(job.id)}
                      className="px-2 py-0.5 text-[10px] rounded border border-eo-brick text-eo-brick hover:bg-eo-brick/10"
                    >Reject</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {filtered.length === 0 && (
        <div className="text-center text-eo-muted py-8">No jobs. Click "Run Analysis" to generate recommendations.</div>
      )}
    </div>
  )
}

function ExecutionTab({ clusterId }: { clusterId: number }) {
  const { data: summary } = useJobSummary(clusterId)
  const { data: jobs, isError, error, refetch } = useJobs(clusterId)
  const { data: concurrency } = useConcurrency(clusterId)
  const execute = useExecuteJob(clusterId)
  const executeAll = useExecuteAll(clusterId)
  const clearQueue = useClearQueue(clusterId)
  const clearHistory = useClearHistory(clusterId)
  const [executeAllMsg, setExecuteAllMsg] = useState<string | null>(null)

  if (!jobs && isError) {
    return <QueryError message={getErrorMessage(error)} onRetry={refetch} />
  }

  const approved = jobs?.filter((j) => j.status === "approved") ?? []
  const queued = jobs?.filter((j) => j.status === "queued") ?? []
  const executing = jobs?.filter((j) => j.status === "executing") ?? []
  const completed = jobs?.filter((j) => j.status === "completed") ?? []
  const failed = jobs?.filter((j) => j.status === "failed") ?? []
  const cap = concurrency?.max_concurrent

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-3">
          <SummaryCard label="Approved" value={summary.approved} color="text-eo-amber" />
          <SummaryCard label="Executing" value={summary.executing} color="text-eo-terracotta" pulse={summary.executing > 0} />
          <SummaryCard label="Completed" value={summary.completed} color="text-eo-sage" />
          <SummaryCard label="Failed" value={summary.failed} color="text-eo-brick" />
        </div>
      )}

      {/* Execute next */}
      {approved.length > 0 && (
        <div className="bg-eo-surface border border-eo-border rounded p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono">Queue ({approved.length} approved)</h3>
            <div className="flex gap-2">
              <button
                onClick={() => { if (approved[0]) execute.mutate(approved[0].id) }}
                disabled={execute.isPending}
                className="px-4 py-1.5 bg-eo-amber text-eo-bg rounded text-sm font-semibold hover:bg-eo-light-amber disabled:opacity-50"
              >Execute Next</button>
              <button
                onClick={() => {
                  setExecuteAllMsg(null)
                  executeAll.mutate(undefined, {
                    onSuccess: (result) => {
                      if (result.skipped > 0) {
                        setExecuteAllMsg(`Queued ${result.queued} · ${result.skipped} skipped (index busy)`)
                      } else {
                        setExecuteAllMsg(null)
                      }
                    },
                  })
                }}
                disabled={executeAll.isPending || approved.length === 0}
                className="px-4 py-1.5 bg-eo-terracotta text-eo-bg rounded text-sm font-semibold hover:opacity-90 disabled:opacity-50"
              >Execute All</button>
              <button
                onClick={() => clearQueue.mutate()}
                disabled={clearQueue.isPending}
                className="px-4 py-1.5 border border-eo-border text-eo-stone rounded text-sm font-semibold hover:text-eo-cream hover:border-eo-muted disabled:opacity-50"
              >Clear Queue</button>
            </div>
          </div>
          {executeAllMsg && (
            <p className="text-xs font-mono text-eo-stone mt-1">{executeAllMsg}</p>
          )}
          <div className="space-y-1 mt-2">
            {approved.slice(0, 50).map((job) => (
              <div key={job.id} className="flex items-center gap-3 text-xs font-mono text-eo-stone py-1">
                <span className="text-eo-amber font-semibold">{TIER_LABELS[job.tier]}</span>
                <span>{job.job_type}</span>
                <JobDestination job={job} />
                <span>{formatBytes(job.pri_store_bytes)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Queued — submitted but waiting on a runner slot */}
      {queued.length > 0 && (
        <div className="bg-eo-surface border border-eo-border rounded p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono">Queued ({queued.length})</h3>
            <button
              onClick={() => clearQueue.mutate()}
              disabled={clearQueue.isPending}
              className="px-3 py-1 border border-eo-border text-eo-stone rounded text-xs font-semibold hover:text-eo-cream hover:border-eo-muted disabled:opacity-50"
            >Clear Queue</button>
          </div>
          <div className="space-y-1">
            {queued.slice(0, 50).map((job) => (
              <div key={job.id} className="flex items-center gap-3 text-xs font-mono text-eo-stone py-1">
                {job.tier > 0 && <span className="text-eo-amber font-semibold">{TIER_LABELS[job.tier] ?? `T${job.tier}`}</span>}
                <span className={cn("px-1.5 py-0.5 rounded text-[10px]", STATUS_STYLES["queued"])}>queued</span>
                <span>{job.job_type}</span>
                <JobDestination job={job} />
                <span>{formatBytes(job.pri_store_bytes)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Running */}
      {executing.length > 0 && (
        <div className="bg-eo-surface border border-eo-terracotta/30 rounded p-4">
          <h3 className="text-xs uppercase tracking-wider text-eo-terracotta font-mono mb-3">
            Running ({executing.length}{cap !== undefined ? `/${cap}` : ""})
          </h3>
          <div className="space-y-2">
            {executing.map((job) => (
              <div key={job.id} className="flex flex-col gap-1">
                <div className="flex items-center gap-3 text-xs font-mono">
                  {job.tier > 0 && <span className="text-eo-amber font-semibold">{TIER_LABELS[job.tier] ?? `T${job.tier}`}</span>}
                  <span className={cn("px-1.5 py-0.5 rounded text-[10px]", STATUS_STYLES["executing"])}>running</span>
                  <span className="text-eo-terracotta">{job.job_type}</span>
                  <JobDestination job={job} />
                  <span className="text-eo-muted font-mono text-[10px] whitespace-nowrap">
                    {job.progress || "running…"}
                  </span>
                </div>
                {/* Indeterminate progress bar */}
                <div className="h-1 w-full rounded-full bg-eo-border overflow-hidden">
                  <div className="h-full w-1/3 rounded-full bg-eo-terracotta animate-indeterminate" />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recently completed */}
      {(completed.length > 0 || failed.length > 0) && (
        <div className="flex justify-end">
          <button
            onClick={() => clearHistory.mutate()}
            disabled={clearHistory.isPending}
            className="px-3 py-1 border border-eo-border text-eo-stone rounded text-xs font-semibold hover:text-eo-cream hover:border-eo-muted disabled:opacity-50"
          >Clear History</button>
        </div>
      )}
      {completed.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono mb-2">Recently Completed</h3>
          <table className="w-full text-xs font-mono">
            <thead className="text-eo-muted">
              <tr className="border-b border-eo-border">
                <th className="text-left py-1 px-2">Status</th>
                <th className="text-left py-1 px-2">Type</th>
                <th className="text-left py-1 px-2">Index</th>
                <th className="text-right py-1 px-2">Size</th>
              </tr>
            </thead>
            <tbody className="text-eo-cream">
              {completed.slice(0, 10).map((job) => (
                <tr key={job.id} className="border-b border-eo-border/30">
                  <td className="py-1 px-2"><span className="text-eo-sage">completed</span></td>
                  <td className="py-1 px-2">{job.job_type}</td>
                  <td className="py-1 px-2 max-w-[300px]"><JobDestination job={job} /></td>
                  <td className="py-1 px-2 text-right">{formatBytes(job.pri_store_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Failed */}
      {failed.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-eo-brick font-mono mb-2">Failed</h3>
          {failed.map((job) => (
            <div key={job.id} className="bg-eo-surface border border-eo-brick/30 rounded p-3 mb-2">
              <div className="flex items-center gap-2 text-xs font-mono text-eo-cream">
                <span className="text-eo-brick font-semibold">{job.job_type}</span>
                <span>{job.index_name}</span>
              </div>
              {job.error_message && <p className="text-xs text-eo-brick/80 mt-1">{job.error_message}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Renders the primary index/node label plus an arrow to the destination when present.
 *  - reindex / promote_index: index_name → target_index
 *  - relocate_shard:          from_node  → to_node
 *  - everything else:         index_name or node_name
 */
function JobDestination({ job }: { job: Job }) {
  if ((job.job_type === "reindex" || job.job_type === "promote_index") && job.target_index) {
    return (
      <span className="truncate flex-1">
        {job.index_name}
        <span className="text-eo-muted mx-1">→</span>
        <span className="text-eo-amber">{job.target_index}</span>
      </span>
    )
  }
  if (job.job_type === "relocate_shard" && job.from_node && job.to_node) {
    return (
      <span className="truncate flex-1">
        {job.from_node}
        <span className="text-eo-muted mx-1">→</span>
        <span className="text-eo-amber">{job.to_node}</span>
      </span>
    )
  }
  return <span className="truncate flex-1">{job.index_name || job.node_name || "—"}</span>
}

function SummaryCard({ label, value, color, pulse }: {
  label: string; value: number; color: string; pulse?: boolean
}) {
  return (
    <div className={cn("bg-eo-surface border border-eo-border rounded p-4", pulse && "animate-pulse-terracotta")}>
      <div className="text-[10px] uppercase tracking-wider text-eo-muted font-mono">{label}</div>
      <div className={cn("text-2xl font-bold font-mono mt-1", color)}>{formatNumber(value)}</div>
    </div>
  )
}

function TierButton({ tier, active, onClick, label }: {
  tier: number | null; active: number | null; onClick: (t: number | null) => void; label: string
}) {
  return (
    <button
      onClick={() => onClick(tier)}
      className={cn(
        "px-2 py-1 rounded text-xs font-mono border transition-colors",
        active === tier ? "border-eo-amber text-eo-amber bg-eo-amber/10" : "border-eo-border text-eo-muted hover:text-eo-stone",
      )}
    >{label}</button>
  )
}
