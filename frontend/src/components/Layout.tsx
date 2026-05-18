import { Link, Outlet, useLocation } from 'react-router-dom'
import { Map, MessageSquare, List, Terminal } from 'lucide-react'

const navItems = [
  { to: '/workspace', label: '工作空间', icon: Terminal },
  { to: '/conversations', label: '对话', icon: MessageSquare },
  { to: '/dashboard', label: '任务', icon: List },
]

export default function Layout() {
  const location = useLocation()
  const isFullHeight = location.pathname.startsWith('/workspace') || location.pathname.startsWith('/conversations')

  return (
    <div className="min-h-screen bg-white">
      <nav className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-full mx-auto px-4">
          <div className="flex justify-between h-12 items-center">
            <div className="flex items-center gap-6">
              <Link to="/" className="flex items-center gap-2">
                <Map className="h-5 w-5 text-blue-600" />
                <span className="text-sm font-bold text-gray-800">OpenGIS</span>
              </Link>
              <div className="flex items-center gap-1">
                {navItems.map(({ to, label, icon: Icon }) => {
                  const active = location.pathname.startsWith(to)
                  return (
                    <Link key={to} to={to}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                        active ? 'bg-blue-50 text-blue-600' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                      }`}>
                      <Icon className="h-4 w-4" />
                      <span className="hidden sm:inline">{label}</span>
                    </Link>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </nav>
      <main className={isFullHeight ? 'overflow-hidden' : 'max-w-7xl mx-auto px-4 py-6'}>
        <Outlet />
      </main>
    </div>
  )
}
