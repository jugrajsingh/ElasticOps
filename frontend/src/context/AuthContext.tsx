import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react"
import { useMe, type UserInfo } from "@/api/auth"
import { UNAUTHORIZED_EVENT } from "@/api/client"

interface AuthContextValue {
  token: string | null
  user: UserInfo | null
  setToken: (token: string | null) => void
  logout: () => void
  isAuthenticated: boolean
  isAdmin: boolean
  isLoading: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => localStorage.getItem("eo_token"))
  const { data: user, isLoading } = useMe()

  const setToken = useCallback((t: string | null) => {
    if (t) {
      localStorage.setItem("eo_token", t)
    } else {
      localStorage.removeItem("eo_token")
    }
    setTokenState(t)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
  }, [setToken])

  // apiFetch dispatches this when a 401 comes back on an authenticated call. localStorage is
  // already cleared by then; this clears the in-memory token so isAuthenticated flips immediately
  // and ProtectedRoute redirects to /login, instead of the app looking "stuck" until a manual refresh.
  useEffect(() => {
    const handleUnauthorized = () => setToken(null)
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [setToken])

  return (
    <AuthContext.Provider value={{
      token,
      user: user ?? null,
      setToken,
      logout,
      isAuthenticated: token !== null,
      isAdmin: user?.role === "admin",
      isLoading,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
