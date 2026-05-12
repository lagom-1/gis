import { Link, Outlet, useLocation } from 'react-router-dom'
import { Map, MessageSquare, List } from 'lucide-react'

const navItems = [
  { to: '/workspace', label: '工作空间', icon: MessageSquare },
  { to: '/dashboard', label: '任务列表', icon: List },
]

export default function Layout() {
  const location = useLocation()
  const isWorkspace = location.pathname.startsWith('/workspace')

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-14">
            <div className="flex items-center">
              <Link to="/" className="flex items-center space-x-2 mr-8">
                <Map className="h-7 w-7 text-primary-600" />
                <span className="text-lg font-bold text-gray-900">OpenGIS</span>
              </Link>
              <div className="flex items-center space-x-1">
                {navItems.map(({ to, label, icon: Icon }) => {
                  const active = location.pathname === to || (to === '/workspace' && isWorkspace)
                  return (
                    <Link
                      key={to}
                      to={to}
                      className={`flex items-center space-x-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                        active
                          ? 'bg-primary-50 text-primary-700'
                          : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                      <span>{label}</span>
                    </Link>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </nav>
      <main className={isWorkspace ? 'overflow-hidden' : 'max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6'}>
        <Outlet />
      </main>
    </div>
  )
}
