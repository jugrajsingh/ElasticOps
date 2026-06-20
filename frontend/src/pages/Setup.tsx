import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { useSetup } from "@/api/auth"

export default function Setup() {
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const { setToken } = useAuth()
  const navigate = useNavigate()
  const setup = useSetup()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    if (password !== confirmPassword) {
      setError("Passwords do not match")
      return
    }
    setup.mutate({ name, email, password }, {
      onSuccess: (data) => {
        setToken(data.access_token)
        navigate("/overview")
      },
      onError: (err) => setError(err.message),
    })
  }

  return (
    <div className="min-h-screen bg-eo-bg flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-3 justify-center mb-8">
          <div className="w-10 h-10 rounded-lg bg-eo-amber flex items-center justify-center">
            <span className="text-eo-bg font-bold text-xl">E</span>
          </div>
          <span className="font-headline font-bold text-2xl text-eo-cream">ElasticOps</span>
        </div>

        <div className="bg-eo-surface border border-eo-border rounded-lg p-6">
          <h2 className="text-lg font-semibold text-eo-cream mb-1">Welcome to ElasticOps</h2>
          <p className="text-xs text-eo-stone mb-6">Create your admin account to get started</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Full Name</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Admin User"
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Email Address</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@elasticops.local"
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Confirm Password</label>
              <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>

            {error && <p className="text-xs text-eo-brick">{error}</p>}

            <button type="submit" disabled={setup.isPending}
              className="w-full py-2 bg-eo-amber text-eo-bg rounded font-semibold text-sm hover:bg-eo-light-amber transition-colors disabled:opacity-50">
              Create Admin Account
            </button>
          </form>

          <p className="text-[10px] text-eo-muted text-center mt-4">
            This account will have full admin privileges
          </p>
        </div>
      </div>
    </div>
  )
}
