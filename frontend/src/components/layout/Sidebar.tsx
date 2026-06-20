import { useState } from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useAuth } from "@/context/AuthContext"
import { useClusterContext } from "@/context/ClusterContext"
import ClusterDialog from "@/components/ClusterDialog"

interface NavItem {
  path: string
  label: string
  icon: string
}

const navItems: NavItem[] = [
  { path: "/overview", label: "Overview", icon: "dashboard" },
  { path: "/shard-map", label: "Shard Map", icon: "grid_view" },
  { path: "/indices", label: "Indices", icon: "list_alt" },
  { path: "/nodes", label: "Nodes", icon: "dns" },
  { path: "/jobs", label: "Jobs", icon: "bolt" },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { isAdmin } = useAuth()

  const bottomNavItems: NavItem[] = [
    ...(isAdmin ? [{ path: "/users", label: "Users", icon: "group" }] : []),
    { path: "/rest", label: "REST", icon: "terminal" },
    { path: "/settings", label: "Settings", icon: "settings" },
  ]

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-full bg-eo-surface border-r border-eo-border flex flex-col z-30 transition-all duration-200 ease-out",
        collapsed ? "w-12" : "w-[200px]",
      )}
    >
      <button
        onClick={onToggle}
        className="flex items-center gap-2 px-3 h-14 border-b border-eo-border hover:bg-eo-border/30 transition-colors"
      >
        <div className="w-7 h-7 rounded bg-eo-amber flex items-center justify-center flex-shrink-0">
          <span className="text-eo-bg font-bold text-sm">E</span>
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="font-headline font-semibold text-eo-cream text-sm">ElasticOps</span>
            <span className="text-[10px] tracking-wide text-eo-muted">Cluster Management</span>
          </div>
        )}
      </button>

      <nav className="flex-1 py-2 flex flex-col gap-0.5">
        {navItems.map((item) => (
          <SidebarLink key={item.path} item={item} collapsed={collapsed} />
        ))}
      </nav>

      <div className="border-t border-eo-border py-2 flex flex-col gap-0.5">
        {bottomNavItems.map((item) => (
          <SidebarLink key={item.path} item={item} collapsed={collapsed} />
        ))}
      </div>

      <ClusterSelector collapsed={collapsed} />
    </aside>
  )
}

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  return (
    <NavLink
      to={item.path}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 px-3 py-2 text-sm transition-colors relative",
          collapsed ? "justify-center" : "",
          isActive
            ? "text-eo-amber border-l-4 border-eo-amber bg-eo-border/50 font-semibold"
            : "text-eo-stone hover:text-eo-cream hover:bg-eo-border/30 border-l-4 border-transparent",
        )
      }
    >
      <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
      {!collapsed && <span>{item.label}</span>}
    </NavLink>
  )
}

function ClusterSelector({ collapsed }: { collapsed: boolean }) {
  const { clusters, activeCluster, setActiveClusterId } = useClusterContext()
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <>
      <div className="border-t border-eo-border px-3 py-3">
        {collapsed ? (
          <div className="flex justify-center">
            <button onClick={() => setDialogOpen(true)} className="group">
              <span className={cn(
                "w-2 h-2 rounded-full block",
                activeCluster ? "bg-eo-sage group-hover:bg-eo-amber" : "bg-eo-muted group-hover:bg-eo-amber",
              )} />
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <select
              value={activeCluster?.id ?? ""}
              onChange={(e) => setActiveClusterId(Number(e.target.value))}
              className="w-full bg-eo-bg border border-eo-border rounded px-2 py-1.5 text-xs font-mono text-eo-stone focus:border-eo-amber focus:outline-none"
            >
              {clusters.length === 0 && <option value="">No clusters</option>}
              {clusters.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <button
              onClick={() => setDialogOpen(true)}
              className="w-full flex items-center justify-center gap-1 py-1 text-[10px] text-eo-muted hover:text-eo-amber border border-eo-border rounded transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">add</span>
              Add Cluster
            </button>
          </div>
        )}
      </div>
      <ClusterDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </>
  )
}
