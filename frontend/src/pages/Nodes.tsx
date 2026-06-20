import { useState, useMemo } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useNodes, useShards, type ShardInfo } from "@/api/es"
import { formatBytes, formatPercent, diskColor, diskTextColor } from "@/lib/format"
import { cn } from "@/lib/utils"

const ROLE_FILTER_OPTIONS = ["All", "hot", "warm", "cold", "data", "master", "coord"] as const

function formatRole(role: string): string {
  if (role === "coord" || role === "-" || role === "") return "coord"
  if (role === "m") return "master"
  if (role.includes("h")) return "hot"
  if (role.includes("w")) return "warm"
  if (role.includes("d")) return "data"
  return role
}

function DiskBar({ percent }: { percent: number }) {
  const color = percent > 85 ? "bg-eo-brick" : percent >= 70 ? "bg-eo-terracotta" : "bg-eo-sage"
  return (
    <div className="inline-block w-16 h-1.5 bg-eo-border rounded-full overflow-hidden align-middle ml-2">
      <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.min(percent, 100)}%` }} />
    </div>
  )
}

type SortKey = "name" | "ip" | "role" | "version" | "disk" | "heap" | "cpu" | "load" | "shards" | "storage"
type SortDir = "asc" | "desc"

export default function Nodes() {
  const { activeCluster } = useClusterContext()
  const { data: nodes } = useNodes(activeCluster?.id ?? null)
  const { data: shards } = useShards(activeCluster?.id ?? null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [filter, setFilter] = useState("")
  const [roleFilter, setRoleFilter] = useState<string>("All")
  const [sortKey, setSortKey] = useState<SortKey>("name")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const shardsByNode = useMemo(() => {
    if (!shards) return new Map<string, ShardInfo[]>()
    const map = new Map<string, ShardInfo[]>()
    for (const s of shards) {
      if (s.node) {
        const list = map.get(s.node) ?? []
        list.push(s)
        map.set(s.node, list)
      }
    }
    return map
  }, [shards])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "name" ? "asc" : "desc")
    }
  }

  const filteredNodes = (nodes ?? []).filter((n) => {
    const matchesText = !filter || n.name.toLowerCase().includes(filter.toLowerCase()) || n.role.includes(filter)
    const matchesRole = roleFilter === "All" || formatRole(n.role) === roleFilter
    return matchesText && matchesRole
  })

  const sortedNodes = useMemo(() => {
    const getVal = (n: (typeof filteredNodes)[number]): string | number => {
      switch (sortKey) {
        case "name": return n.name
        case "ip": return n.ip
        case "role": return formatRole(n.role)
        case "version": return n.version
        case "disk": return n.disk_used_percent
        case "heap": return n.heap_percent
        case "cpu": return n.cpu
        case "load": return n.load_1m
        case "shards": return shardsByNode.get(n.name)?.length ?? 0
        case "storage": return n.disk_used
      }
    }
    return [...filteredNodes].sort((a, b) => {
      const va = getVal(a)
      const vb = getVal(b)
      const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [filteredNodes, sortKey, sortDir, shardsByNode])

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }

  if (!nodes) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Loading nodes...</div>
  }

  const selectedNodeData = nodes.find((n) => n.name === selectedNode)
  const selectedNodeShards = shardsByNode.get(selectedNode ?? "") ?? []

  // Role summaries
  const masterNodes = nodes.filter((n) => n.role.includes("m"))
  const dataNodes = nodes.filter((n) => n.role.includes("d"))
  const coordNodes = nodes.filter((n) => !n.role.includes("d") && !n.role.includes("m"))

  return (
    <div className="flex h-full">
      {/* Main table area */}
      <div className={cn("flex-1 flex flex-col min-w-0 transition-all", selectedNode ? "mr-[450px]" : "")}>
        <div className="p-6 space-y-4 flex-1 overflow-y-auto">
          {/* Role summary cards */}
          <div className="grid grid-cols-3 gap-3">
            <RoleSummaryCard label="Master Nodes" count={masterNodes.length} icon="hub" />
            <RoleSummaryCard label="Data Nodes" count={dataNodes.length} icon="dns" />
            <RoleSummaryCard label="Coordinator Nodes" count={coordNodes.length} icon="mediation" />
          </div>

          {/* Filters */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Filter nodes..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-64 bg-eo-bg border border-eo-border rounded px-3 py-1.5 text-sm font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            />
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="bg-eo-bg border border-eo-border rounded px-3 py-1.5 text-sm font-mono text-eo-cream focus:border-eo-amber focus:outline-none"
            >
              {ROLE_FILTER_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{opt === "All" ? "All Roles" : opt}</option>
              ))}
            </select>
          </div>

          {/* Node table */}
          <table className="w-full text-xs font-mono">
            <thead className="text-eo-muted text-left uppercase tracking-wider">
              <tr className="border-b border-eo-border">
                <th className="py-2 pr-2 w-4"></th>
                <SortHeader label="Node" sortKey="name" current={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="IP" sortKey="ip" current={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Role" sortKey="role" current={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Version" sortKey="version" current={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Disk %" sortKey="disk" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Heap %" sortKey="heap" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="CPU" sortKey="cpu" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Load" sortKey="load" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Shards" sortKey="shards" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
                <SortHeader label="Storage" sortKey="storage" current={sortKey} dir={sortDir} onSort={toggleSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {sortedNodes.map((node) => {
                const nodeShardCount = shardsByNode.get(node.name)?.length ?? 0
                return (
                  <tr
                    key={node.name}
                    onClick={() => setSelectedNode(node.name === selectedNode ? null : node.name)}
                    className={cn(
                      "border-b border-eo-border/50 cursor-pointer transition-colors",
                      node.name === selectedNode
                        ? "bg-eo-amber/5 border-l-2 border-l-eo-terracotta"
                        : "hover:bg-eo-surface/50",
                    )}
                  >
                    <td className="py-2 pr-2">
                      <span className={cn("w-2 h-2 rounded-full inline-block", node.disk_used_percent > 85 ? "bg-eo-brick" : "bg-eo-sage")} />
                    </td>
                    <td className="py-2 pr-3 text-eo-cream">{node.name}</td>
                    <td className="py-2 pr-3 text-eo-stone">{node.ip}</td>
                    <td className="py-2 pr-3 text-eo-stone">{formatRole(node.role)}</td>
                    <td className="py-2 pr-3 text-eo-stone">{node.version}</td>
                    <td className="py-2 pr-3 text-right">
                      <span className={diskTextColor(node.disk_used_percent)}>{formatPercent(node.disk_used_percent)}</span>
                      <DiskBar percent={node.disk_used_percent} />
                    </td>
                    <td className="py-2 pr-3 text-right text-eo-cream">{formatPercent(node.heap_percent)}</td>
                    <td className="py-2 pr-3 text-right text-eo-cream">{node.cpu}%</td>
                    <td className="py-2 pr-3 text-right text-eo-cream">{node.load_1m}</td>
                    <td className="py-2 pr-3 text-right text-eo-cream">{nodeShardCount}</td>
                    <td className="py-2 text-right text-eo-cream">{formatBytes(node.disk_used)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail panel */}
      {selectedNodeData && (
        <div className="fixed right-0 top-14 bottom-0 w-[450px] bg-eo-surface border-l border-eo-border shadow-2xl z-10 overflow-y-auto">
          <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs text-eo-muted font-mono">Nodes &gt; {selectedNodeData.name}</div>
                <h2 className="text-lg font-semibold text-eo-cream mt-1">{selectedNodeData.name}</h2>
                <div className="text-xs text-eo-stone font-mono mt-1">{selectedNodeData.ip} &middot; {formatRole(selectedNodeData.role)} &middot; {selectedNodeData.version}</div>
              </div>
              <button onClick={() => setSelectedNode(null)} className="text-eo-muted hover:text-eo-cream">
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            {/* Metrics grid */}
            <div className="grid grid-cols-2 gap-3">
              <DetailMetric label="Disk Usage" value={formatPercent(selectedNodeData.disk_used_percent)}
                sub={`${formatBytes(selectedNodeData.disk_used)} / ${formatBytes(selectedNodeData.disk_total)}`}
                bar={selectedNodeData.disk_used_percent} barColor={diskColor(selectedNodeData.disk_used_percent)} />
              <DetailMetric label="Heap Usage" value={formatPercent(selectedNodeData.heap_percent)}
                sub={`${formatBytes(selectedNodeData.heap_current)} / ${formatBytes(selectedNodeData.heap_max)}`}
                bar={selectedNodeData.heap_percent} barColor="bg-eo-amber" />
              <DetailMetric label="Shards" value={selectedNodeShards.length.toString()} sub="on this node" />
              <DetailMetric label="Segments" value={selectedNodeData.segments_count.toString()} sub="total" />
            </div>

            {/* Top shards on node */}
            <div>
              <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono mb-2">Top Shards by Size</h3>
              <table className="w-full text-xs font-mono">
                <thead className="text-eo-muted">
                  <tr>
                    <th className="text-left py-1">Index</th>
                    <th className="text-center py-1">Shard</th>
                    <th className="text-center py-1">P/R</th>
                    <th className="text-right py-1">Segs</th>
                    <th className="text-right py-1">Size</th>
                  </tr>
                </thead>
                <tbody className="text-eo-cream">
                  {selectedNodeShards
                    .sort((a, b) => b.store - a.store)
                    .slice(0, 15)
                    .map((s, i) => (
                      <tr key={`${s.index}-${s.shard}-${s.prirep}-${i}`} className="border-t border-eo-border/30">
                        <td className="py-1 truncate max-w-[200px]">{s.index}</td>
                        <td className="py-1 text-center">{s.shard}</td>
                        <td className="py-1 text-center">
                          <span className={cn("px-1 rounded text-[10px]",
                            s.prirep === "p" ? "bg-eo-amber/20 text-eo-amber" : "bg-eo-muted/20 text-eo-stone"
                          )}>{s.prirep === "p" ? "P" : "R"}</span>
                        </td>
                        <td className={cn("py-1 text-right", s.segments_count > 10 ? "text-eo-terracotta" : "")}>
                          {s.segments_count}
                        </td>
                        <td className="py-1 text-right">{formatBytes(s.store)}</td>
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

function SortHeader({ label, sortKey: key, current, dir, onSort, align }: {
  label: string; sortKey: SortKey; current: SortKey; dir: SortDir; onSort: (k: SortKey) => void; align?: "right"
}) {
  const active = current === key
  return (
    <th
      className={cn("py-2 pr-3 cursor-pointer select-none hover:text-eo-cream transition-colors", align === "right" && "text-right")}
      onClick={() => onSort(key)}
    >
      {label}
      {active && <span className="ml-1 text-eo-amber">{dir === "asc" ? "\u25B2" : "\u25BC"}</span>}
    </th>
  )
}

function RoleSummaryCard({ label, count, icon }: { label: string; count: number; icon: string }) {
  return (
    <div className="bg-eo-surface border border-eo-border rounded p-3 flex items-center gap-3">
      <span className="material-symbols-outlined text-eo-amber text-[20px]">{icon}</span>
      <div>
        <div className="text-lg font-semibold font-mono text-eo-cream">{count}</div>
        <div className="text-[10px] uppercase tracking-wider text-eo-muted">{label}</div>
      </div>
    </div>
  )
}

function DetailMetric({ label, value, sub, bar, barColor }: {
  label: string; value: string; sub: string; bar?: number; barColor?: string
}) {
  return (
    <div className="bg-eo-bg rounded p-3">
      <div className="text-[10px] uppercase tracking-wider text-eo-muted font-mono">{label}</div>
      <div className="text-lg font-semibold font-mono text-eo-cream mt-1">{value}</div>
      <div className="text-xs text-eo-stone font-mono">{sub}</div>
      {bar !== undefined && (
        <div className="h-1.5 bg-eo-border rounded-full mt-2 overflow-hidden">
          <div className={cn("h-full rounded-full", barColor)} style={{ width: `${Math.min(bar, 100)}%` }} />
        </div>
      )}
    </div>
  )
}
