import { useEffect, useRef, useState } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useClusterHealth, useSnapshotMeta, useRefreshSnapshots, parseUtc } from "@/api/es"
import { useAuth } from "@/context/AuthContext"
import { useChangePassword } from "@/api/auth"
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

/** A whole-second tick so the "updated Ns ago" label and the poll countdown advance live. */
function useNowTick(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function formatAgo(seconds: number): string {
  if (seconds < 1) return "just now"
  if (seconds < 60) return `${seconds}s ago`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  if (m < 60) return s > 0 ? `${m}m ${s}s ago` : `${m}m ago`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m ago`
}

/**
 * Live freshness readout + icon-only force-refresh.
 *
 * `updated Ns ago` is the true snapshot age (from `fetched_at`). `next in Ns` counts down to the
 * next *client* auto-refresh and matches the dropdown cadence — it's derived from the health query's
 * `dataUpdatedAt`, so it naturally resets when the query refetches (including the force button).
 * When auto-refresh is "Off" it reads `auto off`. The force button is the only control that re-polls
 * the live cluster; the auto-refresh only re-reads the cached snapshot.
 */
function StalenessIndicator({ clusterId, refreshInterval }: { clusterId: number; refreshInterval: number }) {
  const metaQuery = useSnapshotMeta(clusterId)
  const meta = metaQuery.data
  const refresh = useRefreshSnapshots(clusterId)
  const now = useNowTick()

  if (!meta) return null

  // True snapshot age from `fetched_at`, ticking against the live clock; fall back to the
  // server-reported `stale_seconds` if the timestamp can't be parsed.
  const fetchedMs = parseUtc(meta.fetched_at)
  const ageSeconds = Number.isNaN(fetchedMs)
    ? meta.stale_seconds
    : Math.max(0, Math.round((now - fetchedMs) / 1000))

  const autoOn = refreshInterval > 0
  const nextInSeconds = autoOn
    ? Math.max(0, Math.ceil((refreshInterval - (now - metaQuery.dataUpdatedAt)) / 1000))
    : null

  const stale = ageSeconds > 90
  const refreshing = refresh.isPending

  return (
    <div className="flex items-center gap-2 text-[10px] font-mono">
      <span className="flex items-center gap-1.5" title={`Snapshot fetched ${formatAgo(ageSeconds)}`}>
        <span className={cn("w-1.5 h-1.5 rounded-full", stale ? "bg-eo-terracotta" : "bg-eo-sage")} />
        <span className={cn(stale ? "text-eo-terracotta" : "text-eo-stone")}>
          updated {formatAgo(ageSeconds)}
        </span>
        {autoOn ? (
          <span className="text-eo-muted">· next in {nextInSeconds}s</span>
        ) : (
          <span className="text-eo-muted">· auto off</span>
        )}
      </span>
      <button
        onClick={() => refresh.mutate()}
        disabled={refreshing}
        title="Force a live refresh now (re-polls the cluster) and reset the countdown"
        aria-label="Force refresh now"
        className={cn(
          "flex items-center justify-center w-6 h-6 rounded border transition-colors",
          refreshing
            ? "border-eo-border text-eo-muted cursor-wait"
            : "border-eo-border text-eo-stone hover:text-eo-amber hover:border-eo-amber",
        )}
      >
        <span className={cn("material-symbols-outlined text-[14px]", refreshing && "animate-spin")}>refresh</span>
      </button>
    </div>
  )
}

export default function TopBar({ sidebarWidth }: TopBarProps) {
  const { activeCluster, refreshInterval, setRefreshInterval } = useClusterContext()
  const { data: health } = useClusterHealth(activeCluster?.id ?? null)
  const { isAuthenticated } = useAuth()

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
              {activeCluster.read_only && (
                <span className="px-1 py-px rounded border border-eo-terracotta text-eo-terracotta text-[9px] font-mono leading-none">
                  read-only
                </span>
              )}
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
        {activeCluster && (
          <StalenessIndicator clusterId={activeCluster.id} refreshInterval={refreshInterval} />
        )}

        <select
          value={refreshInterval}
          onChange={(e) => setRefreshInterval(Number(e.target.value))}
          title="Auto-refresh interval — how often the page re-reads the cached snapshot ('Off' to freeze)"
          className="bg-transparent border border-eo-border rounded px-1.5 py-0.5 text-[10px] font-mono text-eo-stone focus:border-eo-amber focus:outline-none"
        >
          {REFRESH_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        {isAuthenticated && <AccountMenu />}
      </div>
    </header>
  )
}

function AccountMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-eo-stone hover:text-eo-cream transition-colors"
        title="Account"
      >
        <span className="material-symbols-outlined text-[18px]">account_circle</span>
        {user?.name && <span className="text-[11px] font-mono max-w-[120px] truncate">{user.name}</span>}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-48 bg-eo-surface border border-eo-border rounded-lg shadow-lg py-1 z-30">
          {user && (
            <div className="px-3 py-2 border-b border-eo-border">
              <p className="text-xs text-eo-cream truncate">{user.name}</p>
              <p className="text-[10px] text-eo-muted font-mono truncate">{user.email}</p>
            </div>
          )}
          <button
            onClick={() => {
              setShowPassword(true)
              setOpen(false)
            }}
            className="w-full text-left px-3 py-2 text-xs text-eo-stone hover:bg-eo-bg hover:text-eo-cream transition-colors flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">password</span>
            Change password
          </button>
          <button
            onClick={logout}
            className="w-full text-left px-3 py-2 text-xs text-eo-stone hover:bg-eo-bg hover:text-eo-cream transition-colors flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">logout</span>
            Logout
          </button>
        </div>
      )}

      {showPassword && <ChangePasswordDialog onClose={() => setShowPassword(false)} />}
    </div>
  )
}

function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)
  const changePassword = useChangePassword()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match")
      return
    }
    changePassword.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: () => setSuccess(true),
        onError: (err) => setError(err.message),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-eo-surface border border-eo-border rounded-lg w-full max-w-sm p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-eo-cream">Change Password</h2>
          <button onClick={onClose} className="text-eo-muted hover:text-eo-cream">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {success ? (
          <div className="space-y-4">
            <p className="text-sm text-eo-sage flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px]">check_circle</span>
              Password updated.
            </p>
            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm bg-eo-amber text-eo-bg rounded font-semibold hover:bg-eo-light-amber transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">
                Current Password
              </label>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">
                New Password
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required
                minLength={8}
              />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">
                Confirm New Password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required
                minLength={8}
              />
            </div>

            {error && <p className="text-xs text-eo-brick">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm text-eo-stone border border-eo-border rounded hover:text-eo-cream transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={changePassword.isPending}
                className="px-4 py-2 text-sm bg-eo-amber text-eo-bg rounded font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50"
              >
                Update Password
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
