import { useState, useEffect } from "react"
import { useCreateCluster, type ClusterCreate } from "@/api/clusters"

interface ClusterDialogProps {
  open: boolean
  onClose: () => void
}

export default function ClusterDialog({ open, onClose }: ClusterDialogProps) {
  const [name, setName] = useState("")
  const [url, setUrl] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [verifySsl, setVerifySsl] = useState(true)
  const [error, setError] = useState("")
  const createCluster = useCreateCluster()

  useEffect(() => {
    if (open) {
      setName("")
      setUrl("")
      setUsername("")
      setPassword("")
      setVerifySsl(true)
      setError("")
    }
  }, [open])

  if (!open) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    const data: ClusterCreate = { name, url, username: username || undefined, password: password || undefined, verify_ssl: verifySsl }
    createCluster.mutate(data, {
      onSuccess: () => onClose(),
      onError: (err) => setError(err.message),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-eo-surface border border-eo-border rounded-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold text-eo-cream mb-4">Add Cluster</h2>
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
              placeholder="Password (optional)"
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

          {error && <p className="text-xs text-eo-brick">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-eo-stone border border-eo-border rounded hover:text-eo-cream transition-colors"
            >Cancel</button>
            <button
              type="submit"
              disabled={createCluster.isPending}
              className="px-4 py-2 text-sm bg-eo-amber text-eo-bg rounded font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50"
            >Add Cluster</button>
          </div>
        </form>
      </div>
    </div>
  )
}
