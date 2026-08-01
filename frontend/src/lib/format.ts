export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

export function formatPercent(n: number): string {
  return `${n.toFixed(1)}%`
}

export function healthColor(status: string): string {
  switch (status) {
    case "green": return "bg-eo-sage"
    case "yellow": return "bg-eo-terracotta"
    case "red": return "bg-eo-brick"
    default: return "bg-eo-muted"
  }
}

export function diskColor(percent: number): string {
  if (percent >= 85) return "bg-eo-brick"
  if (percent >= 70) return "bg-eo-terracotta"
  return "bg-eo-sage"
}

export function diskTextColor(percent: number): string {
  if (percent >= 85) return "text-eo-brick"
  if (percent >= 70) return "text-eo-terracotta"
  return "text-eo-sage"
}

/** Relative "since" label from a naive-UTC ISO timestamp (e.g. `unassigned.at`); "-" when absent. */
export function formatSince(iso: string | null): string {
  if (!iso) return "-"
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso)
  const ms = new Date(hasTz ? iso : `${iso}Z`).getTime()
  if (Number.isNaN(ms)) return "-"
  const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
