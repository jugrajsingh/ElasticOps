import { useMemo, useState } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useClusterSettings, useUpdateSettings } from "@/api/es"
import { cn } from "@/lib/utils"

interface SettingRow {
  key: string
  scope: "persistent" | "transient" | "default"
  value: string
  defaultValue: string
  isModified: boolean
}

const QUICK_ACTIONS = [
  {
    label: "Speed Up Rebalancing",
    icon: "speed",
    description: "Set concurrent rebalance to 10, recoveries to 4",
    settings: {
      "cluster.routing.allocation.cluster_concurrent_rebalance": "10",
      "cluster.routing.allocation.node_concurrent_incoming_recoveries": "4",
      "cluster.routing.allocation.node_concurrent_outgoing_recoveries": "4",
    },
  },
  {
    label: "Enable Disk Balancing",
    icon: "storage",
    description: "Set balance.disk_usage to 0.5 (default is near-zero)",
    settings: {
      "cluster.routing.allocation.balance.disk_usage": "0.5",
    },
  },
  {
    label: "Reset All Transient",
    icon: "restart_alt",
    description: "Clear all transient settings (revert to persistent + defaults)",
    settings: null,
    danger: true,
  },
]

export default function Settings() {
  const { activeCluster } = useClusterContext()
  const { data: settings, isLoading } = useClusterSettings(activeCluster?.id ?? null)
  const updateSettings = useUpdateSettings(activeCluster?.id ?? null)
  const [filter, setFilter] = useState("")

  const rows = useMemo<SettingRow[]>(() => {
    if (!settings) return []
    const allKeys = new Set<string>()
    const result: SettingRow[] = []

    // Collect modified settings first
    for (const [key, value] of Object.entries(settings.persistent)) {
      allKeys.add(key)
      result.push({
        key,
        scope: "persistent",
        value,
        defaultValue: settings.defaults[key] ?? "",
        isModified: true,
      })
    }
    for (const [key, value] of Object.entries(settings.transient)) {
      if (allKeys.has(key)) continue
      allKeys.add(key)
      result.push({
        key,
        scope: "transient",
        value,
        defaultValue: settings.defaults[key] ?? "",
        isModified: true,
      })
    }

    // Add defaults that match filter
    if (filter) {
      for (const [key, value] of Object.entries(settings.defaults)) {
        if (allKeys.has(key)) continue
        if (key.toLowerCase().includes(filter.toLowerCase())) {
          result.push({
            key,
            scope: "default",
            value,
            defaultValue: value,
            isModified: false,
          })
        }
      }
    }

    return result
  }, [settings, filter])

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }
  if (isLoading) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Loading settings...</div>
  }

  const modifiedCount = rows.filter((r) => r.isModified).length

  const handleReset = (key: string, scope: "persistent" | "transient") => {
    updateSettings.mutate({ [scope]: { [key]: null } })
  }

  const handleQuickAction = (action: (typeof QUICK_ACTIONS)[number]) => {
    if (action.settings === null) {
      // Reset all transient
      if (!settings) return
      const nulled: Record<string, null> = {}
      for (const key of Object.keys(settings.transient)) {
        nulled[key] = null
      }
      updateSettings.mutate({ transient: nulled })
    } else {
      updateSettings.mutate({ transient: action.settings as unknown as Record<string, string | null> })
    }
  }

  return (
    <div className="p-6 space-y-6 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-eo-cream">Cluster Settings</h2>
          <p className="text-xs text-eo-stone font-mono mt-1">{modifiedCount} modified settings</p>
        </div>
        <input
          type="text"
          placeholder="Search settings..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-64 bg-eo-bg border border-eo-border rounded px-3 py-1.5 text-sm font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
        />
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Settings table (2/3) */}
        <div className="col-span-2 space-y-4">
          {/* Modified settings */}
          {rows.filter((r) => r.isModified).length > 0 && (
            <div className="border border-eo-amber/30 rounded overflow-hidden">
              <div className="bg-eo-amber/5 px-4 py-2 border-b border-eo-amber/20">
                <span className="text-xs font-mono text-eo-amber uppercase tracking-wider">Modified Settings</span>
              </div>
              <table className="w-full text-xs font-mono">
                <thead className="text-eo-muted uppercase tracking-wider">
                  <tr className="border-b border-eo-border">
                    <th className="py-2 px-3 text-left w-12">Scope</th>
                    <th className="py-2 px-3 text-left">Setting</th>
                    <th className="py-2 px-3 text-left">Default</th>
                    <th className="py-2 px-3 text-left">Current</th>
                    <th className="py-2 px-3 text-right w-16">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.filter((r) => r.isModified).map((row) => (
                    <tr key={row.key} className="border-b border-eo-border/30 hover:bg-eo-surface/50">
                      <td className="py-1.5 px-3">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold",
                          row.scope === "persistent" ? "bg-eo-terracotta/20 text-eo-terracotta" : "bg-eo-sage/20 text-eo-sage"
                        )}>{row.scope === "persistent" ? "P" : "T"}</span>
                      </td>
                      <td className="py-1.5 px-3 text-eo-cream">{row.key}</td>
                      <td className="py-1.5 px-3 text-eo-muted">{row.defaultValue || "-"}</td>
                      <td className="py-1.5 px-3 text-eo-amber">{row.value}</td>
                      <td className="py-1.5 px-3 text-right">
                        <button
                          onClick={() => handleReset(row.key, row.scope as "persistent" | "transient")}
                          className="text-[10px] text-eo-stone hover:text-eo-cream border border-eo-border rounded px-2 py-0.5"
                        >Reset</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Default settings (filtered) */}
          {rows.filter((r) => !r.isModified).length > 0 && (
            <div className="bg-eo-surface border border-eo-border rounded overflow-hidden">
              <div className="px-4 py-2 border-b border-eo-border">
                <span className="text-xs font-mono text-eo-muted uppercase tracking-wider">Defaults matching "{filter}"</span>
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                <table className="w-full text-xs font-mono">
                  <tbody>
                    {rows.filter((r) => !r.isModified).map((row) => (
                      <tr key={row.key} className="border-b border-eo-border/20 hover:bg-eo-bg/50">
                        <td className="py-1 px-3 text-eo-stone">{row.key}</td>
                        <td className="py-1 px-3 text-eo-muted text-right">{row.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {filter && rows.length === 0 && (
            <div className="text-center text-eo-muted py-8">No settings match "{filter}"</div>
          )}
        </div>

        {/* Quick Actions (1/3) */}
        <div className="space-y-3">
          <h3 className="text-xs uppercase tracking-wider text-eo-muted font-mono">Quick Actions</h3>
          {QUICK_ACTIONS.map((action) => (
            <button
              key={action.label}
              onClick={() => handleQuickAction(action)}
              disabled={updateSettings.isPending}
              className={cn(
                "w-full text-left bg-eo-surface border rounded p-4 transition-colors group",
                action.danger
                  ? "border-eo-brick/30 hover:border-eo-brick/60"
                  : "border-eo-border hover:border-eo-amber/40",
              )}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={cn("material-symbols-outlined text-[18px]", action.danger ? "text-eo-brick" : "text-eo-amber")}>{action.icon}</span>
                <span className={cn("text-sm font-semibold", action.danger ? "text-eo-brick" : "text-eo-cream")}>{action.label}</span>
              </div>
              <p className="text-xs text-eo-stone">{action.description}</p>
            </button>
          ))}

          {/* Info */}
          <div className="bg-eo-surface border border-eo-border rounded p-3 mt-4">
            <p className="text-[10px] text-eo-muted leading-relaxed">
              <span className="text-eo-terracotta font-semibold">P</span> = Persistent (survives restart).
              <span className="text-eo-sage font-semibold ml-2">T</span> = Transient (resets on restart).
              Quick actions use transient settings by default.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
