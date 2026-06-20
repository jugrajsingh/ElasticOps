import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { useLogin } from "@/api/auth"

export default function Login() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const { setToken } = useAuth()
  const navigate = useNavigate()
  const login = useLogin()

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    login.mutate({ email, password }, {
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
          <h2 className="text-lg font-semibold text-eo-cream mb-1">Sign In</h2>
          <p className="text-xs text-eo-stone mb-6">Access your dashboard</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Email Address</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-eo-muted font-mono block mb-1">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
                required />
            </div>

            {error && <p className="text-xs text-eo-brick">{error}</p>}

            <button type="submit" disabled={login.isPending}
              className="w-full py-2 bg-eo-amber text-eo-bg rounded font-semibold text-sm hover:bg-eo-light-amber transition-colors disabled:opacity-50">
              Sign In
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
