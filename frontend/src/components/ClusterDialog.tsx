import { useState, useEffect } from "react"
import { useCreateCluster, useUpdateCluster, type Cluster, type ClusterCreate } from "@/api/clusters"
import { useClusterContext } from "@/context/ClusterContext"

interface ClusterDialogProps {
  open: boolean
  onClose: () => void
  cluster?: Cluster | null
}

export default function ClusterDialog({ open, onClose, cluster }: ClusterDialogProps) {
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [verifySsl, setVerifySsl] = useState(true)
  const [readOnly, setReadOnly] = useState(false)
  const [isActive, setIsActive] = useState(true)
  const [error, setError] = useState("")
  const createCluster = useCreateCluster()
  const updateCluster = useUpdateCluster()
  const { setActiveClusterId } = useClusterContext()
  const isEdit = !!cluster

  useEffect(() => {
    if (open) {
      setName(cluster?.name ?? "")
      setUrl(cluster?.url ?? "")
      setUsername(cluster?.username ?? "")
      setPassword("")
      setVerifySsl(cluster?.verify_ssl ?? true)
      setReadOnly(cluster?.read_only ?? false)
      setIsActive(cluster?.is_active ?? true)
      setError("")
    }
  }, [open, cluster])

  if (!open) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (isEdit && cluster) {
      const data: Partial<ClusterCreate> = { name, url, username, verify_ssl: verifySsl, read_only: readOnly, is_active: isActive }
      if (password) data.password = password
      updateCluster.mutate({ id: cluster.id, data }, {
        onSuccess: () => onClose(),
        onError: (err) => setError(err.message),
      })
      return
    }
    const data: ClusterCreate = { name, url, username: username || undefined, password: password || undefined, verify_ssl: verifySsl, read_only: readOnly }
    createCluster.mutate(data, {
      onSuccess: (created) => {
        setActiveClusterId(created.id)
        onClose()
      },
      onError: (err) => setError(err.message),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-eo-surface border border-eo-border rounded-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-eo-cream mb-4">{isEdit ? "Edit Cluster" : "Add Cluster"}</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Cluster name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            required
          />
          <input
            type="url"
            placeholder="https://elasticsearch:9200"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            required
          />
          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="Username (optional)"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            />
            <input
              type="password"
              placeholder={isEdit ? "Password (unchanged)" : "Password (optional)"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-eo-stone">
            <input
              type="checkbox"
              checked={verifySsl}
              onChange={(e) => setVerifySsl(e.target.checked)}
              className="rounded border-eo-border bg-eo-bg text-eo-amber focus:ring-eo-amber"
            />
            Verify SSL
          </label>
          <label className="flex items-center gap-2 text-sm text-eo-stone">
            <input
              type="checkbox"
              checked={readOnly}
              onChange={(e) => setReadOnly(e.target.checked)}
              className="rounded border-eo-border bg-eo-bg text-eo-amber focus:ring-eo-amber"
            />
            Read-only (block all writes)
          </label>
          {isEdit && (
            <label className="flex items-center gap-2 text-sm text-eo-stone">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="rounded border-eo-border bg-eo-bg text-eo-amber focus:ring-eo-amber"
              />
              Active (cluster is enabled)
            </label>
          )}

          {error && <p className="text-xs text-eo-brick">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-eo-stone border border-eo-border rounded hover:text-eo-cream transition-colors"
            >Cancel</button>
            <button
              type="submit"
              disabled={createCluster.isPending || updateCluster.isPending}
              className="px-4 py-2 text-sm bg-eo-amber text-eo-bg rounded font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50"
            >{isEdit ? "Save Changes" : "Add Cluster"}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
