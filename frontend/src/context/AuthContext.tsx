import { createContext, useContext, useState, useCallback, type ReactNode } from "react"
import { useMe, type UserInfo } from "@/api/auth"

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
