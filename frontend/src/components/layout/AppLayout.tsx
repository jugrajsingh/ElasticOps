import { useState } from "react"
import { Outlet, useLocation } from "react-router-dom"
import Sidebar from "./Sidebar"
import TopBar from "./TopBar"

const COLLAPSED_PAGES = ["/shard-map"]

export default function AppLayout() {
  const location = useLocation()
  const autoCollapse = COLLAPSED_PAGES.some((p) => location.pathname.startsWith(p))
  const [manualCollapsed, setManualCollapsed] = useState(false)
  const collapsed = autoCollapse || manualCollapsed

  const sidebarWidth = collapsed ? 48 : 200

  return (
    <div className="h-screen overflow-hidden bg-eo-bg">
      <Sidebar collapsed={collapsed} onToggle={() => setManualCollapsed((c) => !c)} />
      <TopBar sidebarWidth={sidebarWidth} />
      <main
        className="pt-14 h-screen overflow-auto transition-all duration-200"
        style={{ marginLeft: sidebarWidth }}
      >
        <Outlet />
      </main>
    </div>
  )
}
