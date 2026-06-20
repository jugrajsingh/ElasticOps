import { useState } from "react"
import { useAuth } from "@/context/AuthContext"
import { useAdminUsers, useInviteUser, useDeleteUser, type UserDetail } from "@/api/auth"
import { useClusters } from "@/api/clusters"
import { cn } from "@/lib/utils"

export default function Users() {
  const { isAdmin } = useAuth()
  const { data: users } = useAdminUsers()
  const { data: clusters } = useClusters()
  const [showInvite, setShowInvite] = useState(false)

  if (!isAdmin) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Admin access required</div>
  }

  return (
    <div className="p-6 space-y-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-eo-cream">User Management</h2>
          <p className="text-xs text-eo-stone font-mono mt-1">{users?.length ?? 0} users</p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="px-4 py-2 bg-eo-amber text-eo-bg rounded text-sm font-semibold hover:bg-eo-light-amber transition-colors"
        >Invite User</button>
      </div>

      <table className="w-full text-xs font-mono">
        <thead className="text-eo-muted text-left uppercase tracking-wider">
          <tr className="border-b border-eo-border">
            <th className="py-2 px-2">Name</th>
            <th className="py-2 px-2">Email</th>
            <th className="py-2 px-2">Role</th>
            <th className="py-2 px-2">Clusters</th>
            <th className="py-2 px-2">Created</th>
            <th className="py-2 px-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="text-eo-cream">
          {users?.map((user) => (
            <UserRow key={user.id} user={user} clusters={clusters ?? []} />
          ))}
        </tbody>
      </table>

      {showInvite && (
        <InviteDialog clusters={clusters ?? []} onClose={() => setShowInvite(false)} />
      )}
    </div>
  )
}

function UserRow({ user, clusters }: { user: UserDetail; clusters: { id: number; name: string }[] }) {
  const deleteUser = useDeleteUser()
  const clusterNames = user.cluster_ids.map(
    (id) => clusters.find((c) => c.id === id)?.name ?? `#${id}`,
  )

  return (
    <tr className="border-b border-eo-border/30 hover:bg-eo-surface/50">
      <td className="py-2 px-2 text-eo-cream">{user.name}</td>
      <td className="py-2 px-2 text-eo-stone">{user.email}</td>
      <td className="py-2 px-2">
        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold",
          user.role === "admin" ? "bg-eo-amber/20 text-eo-amber" : "bg-eo-muted/20 text-eo-stone"
        )}>{user.role}</span>
      </td>
      <td className="py-2 px-2">
        <div className="flex gap-1 flex-wrap">
          {user.role === "admin" ? (
            <span className="px-1.5 py-0.5 rounded text-[10px] bg-eo-amber/10 text-eo-amber">All clusters</span>
          ) : clusterNames.length > 0 ? (
            clusterNames.map((name) => (
              <span key={name} className="px-1.5 py-0.5 rounded text-[10px] bg-eo-surface border border-eo-border text-eo-stone">{name}</span>
            ))
          ) : (
            <span className="text-eo-muted">No clusters</span>
          )}
        </div>
      </td>
      <td className="py-2 px-2 text-eo-muted">{new Date(user.created_at).toLocaleDateString()}</td>
      <td className="py-2 px-2 text-right">
        {user.role !== "admin" && (
          <button
            onClick={() => deleteUser.mutate(user.id)}
            className="text-eo-muted hover:text-eo-brick transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">delete</span>
          </button>
        )}
      </td>
    </tr>
  )
}

function InviteDialog({ clusters, onClose }: { clusters: { id: number; name: string }[]; onClose: () => void }) {
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState("user")
  const [selectedClusters, setSelectedClusters] = useState<number[]>([])
  const [error, setError] = useState("")
  const invite = useInviteUser()

  const toggleCluster = (id: number) => {
    setSelectedClusters((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    )
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    invite.mutate({ name, email, password, role, cluster_ids: selectedClusters }, {
      onSuccess: () => onClose(),
      onError: (err) => setError(err.message),
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-eo-surface border border-eo-border rounded-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-eo-cream">Invite User</h2>
          <button onClick={onClose} className="text-eo-muted hover:text-eo-cream">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Full Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sarah Chen"
              className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none" required />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Email Address</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@company.com"
              className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none" required />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Temporary Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none" required />
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-2">Cluster Access</label>
            <div className="space-y-1">
              {clusters.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm text-eo-stone cursor-pointer hover:text-eo-cream">
                  <input type="checkbox" checked={selectedClusters.includes(c.id)}
                    onChange={() => toggleCluster(c.id)}
                    className="rounded border-eo-border bg-eo-bg text-eo-amber focus:ring-eo-amber" />
                  {c.name}
                </label>
              ))}
              {clusters.length === 0 && <p className="text-xs text-eo-muted">No clusters configured yet</p>}
            </div>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}
              className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream focus:border-eo-amber focus:outline-none">
              <option value="user">Standard User</option>
              <option value="admin">Admin</option>
            </select>
          </div>

          {error && <p className="text-xs text-eo-brick">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="px-4 py-2 text-sm text-eo-stone border border-eo-border rounded hover:text-eo-cream transition-colors">Cancel</button>
            <button type="submit" disabled={invite.isPending}
              className="px-4 py-2 text-sm bg-eo-amber text-eo-bg rounded font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50">
              Provision User
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
