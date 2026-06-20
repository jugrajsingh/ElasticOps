import { useClusterContext } from "@/context/ClusterContext"
import { useClusterHealth } from "@/api/es"
import { useAuth } from "@/context/AuthContext"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

const REFRESH_OPTIONS = [
  { label: "5s", value: 5000 },
  { label: "15s", value: 15000 },
  { label: "30s", value: 30000 },
  { label: "1m", value: 60000 },
  { label: "Off", value: 0 },
]

interface TopBarProps {
  sidebarWidth: number
}

export default function TopBar({ sidebarWidth }: TopBarProps) {
  const { activeCluster, refreshInterval, setRefreshInterval } = useClusterContext()
  const { data: health } = useClusterHealth(activeCluster?.id ?? null)
  const { logout, isAuthenticated } = useAuth()

  const statusColor = health
    ? { green: "bg-eo-sage", yellow: "bg-eo-terracotta", red: "bg-eo-brick" }[health.status] ?? "bg-eo-muted"
    : "bg-eo-muted"

  return (
    <header
      className="fixed top-0 right-0 h-14 bg-eo-surface/80 backdrop-blur-md border-b border-eo-border flex items-center justify-between px-6 z-20 transition-all duration-200"
      style={{ left: sidebarWidth }}
    >
      <div className="flex items-center gap-6 text-[10px] uppercase tracking-wider font-mono text-eo-stone">
        {activeCluster && health ? (
          <>
            <span className="flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", statusColor)} />
              {health.cluster_name}
            </span>
            <span>{health.number_of_nodes} nodes</span>
            <span>{formatNumber(health.active_shards)} shards</span>
            {health.relocating_shards > 0 && (
              <span className="text-eo-terracotta">{health.relocating_shards} relocating</span>
            )}
            {health.unassigned_shards > 0 && (
              <span className="text-eo-brick">{health.unassigned_shards} unassigned</span>
            )}
          </>
        ) : activeCluster ? (
          <span>Connecting...</span>
        ) : (
          <span>No cluster connected</span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <span className="material-symbols-outlined text-[16px] text-eo-muted">autorenew</span>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value))}
            className="bg-transparent border border-eo-border rounded px-1.5 py-0.5 text-[10px] font-mono text-eo-stone focus:border-eo-amber focus:outline-none"
          >
            {REFRESH_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {isAuthenticated && (
          <button
            onClick={logout}
            className="text-eo-muted hover:text-eo-cream transition-colors"
            title="Logout"
          >
            <span className="material-symbols-outlined text-[18px]">logout</span>
          </button>
        )}
      </div>
    </header>
  )
}
