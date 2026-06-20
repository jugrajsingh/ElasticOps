import { createContext, useContext, useState, useEffect, type ReactNode } from "react"
import { type Cluster, useClusters } from "@/api/clusters"

interface ClusterContextValue {
  clusters: Cluster[]
  activeCluster: Cluster | null
  setActiveClusterId: (id: number) => void
  isLoading: boolean
  refreshInterval: number
  setRefreshInterval: (ms: number) => void
}

const ClusterContext = createContext<ClusterContextValue | null>(null)

export function ClusterProvider({ children }: { children: ReactNode }) {
  const { data: clusters = [], isLoading } = useClusters()
  const [activeId, setActiveId] = useState<number | null>(() => {
    const saved = localStorage.getItem("eo_active_cluster")
    return saved ? Number(saved) : null
  })
  const [refreshInterval, setRefreshInterval] = useState<number>(() => {
    const saved = localStorage.getItem("eo_refresh_interval")
    return saved ? Number(saved) : 15000
  })

  const activeCluster = clusters.find((c) => c.id === activeId) ?? clusters[0] ?? null

  useEffect(() => {
    if (activeId !== null) {
      localStorage.setItem("eo_active_cluster", String(activeId))
    }
  }, [activeId])

  useEffect(() => {
    localStorage.setItem("eo_refresh_interval", String(refreshInterval))
  }, [refreshInterval])

  return (
    <ClusterContext.Provider
      value={{
        clusters,
        activeCluster,
        setActiveClusterId: setActiveId,
        isLoading,
        refreshInterval,
        setRefreshInterval,
      }}
    >
      {children}
    </ClusterContext.Provider>
  )
}

export function useClusterContext() {
  const ctx = useContext(ClusterContext)
  if (!ctx) throw new Error("useClusterContext must be used within ClusterProvider")
  return ctx
}
