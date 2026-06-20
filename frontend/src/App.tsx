import { Routes, Route, Navigate } from "react-router-dom"
import { useAuth } from "./context/AuthContext"
import { useAuthStatus } from "./api/auth"
import AppLayout from "./components/layout/AppLayout"
import Login from "./pages/Login"
import Setup from "./pages/Setup"
import Overview from "./pages/Overview"
import ShardMap from "./pages/ShardMap"
import Indices from "./pages/Indices"
import Nodes from "./pages/Nodes"
import Jobs from "./pages/Jobs"
import Settings from "./pages/Settings"
import Rest from "./pages/Rest"
import Users from "./pages/Users"

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  const { data: status, isLoading } = useAuthStatus()
  if (isLoading) return null
  if (status?.setup_required) return <Navigate to="/setup" replace />
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: status, isLoading } = useAuthStatus()
  if (isLoading) return null
  if (status?.setup_required) return <Navigate to="/setup" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route path="/login" element={<AuthGate><Login /></AuthGate>} />
      <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<Overview />} />
        <Route path="/shard-map" element={<ShardMap />} />
        <Route path="/indices" element={<Indices />} />
        <Route path="/nodes" element={<Nodes />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/rest" element={<Rest />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/users" element={<Users />} />
      </Route>
    </Routes>
  )
}
