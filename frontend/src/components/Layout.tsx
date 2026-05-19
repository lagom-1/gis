import { Link, Outlet, useLocation } from 'react-router-dom'
import { Map, MessageSquare, Terminal } from 'lucide-react'
import { useAppStore } from '../stores/appStore'

const STATIC_NAV = [
  { to: '/workspace', label: '工作空间', icon: Terminal },
]

export default function Layout() {
  const location = useLocation()
  const isFullHeight = location.pathname.startsWith('/workspace') || location.pathname.startsWith('/conversations')
  const activeConversationId = useAppStore(s => s.activeConversationId)
  const convTo = activeConversationId ? `/conversations/${activeConversationId}` : '/conversations'

  return (
    <div className="min-h-screen bg-stone-50">
      <nav className="bg-white/80 backdrop-blur-sm border-b border-stone-200 sticky top-0 z-50">
        <div className="max-w-full mx-auto px-4">
          <div className="flex justify-between h-14 items-center">
            <div className="flex items-center gap-6">
              <Link to="/" className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-emerald-100 flex items-center justify-center">
                  <Map className="h-4 w-4 text-emerald-600" />
                </div>
                <span className="text-sm font-bold text-stone-800">OpenGIS</span>
              </Link>
              <div className="flex items-center gap-1">
                {STATIC_NAV.map(({ to, label, icon: Icon }) => {
                  const active = location.pathname.startsWith(to)
                  return (
                    <Link key={to} to={to}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                        active
                          ? 'bg-emerald-50 text-emerald-700'
                          : 'text-stone-500 hover:text-stone-700 hover:bg-stone-50'
                      }`}>
                      <Icon className="h-4 w-4" />
                      <span className="hidden sm:inline">{label}</span>
                    </Link>
                  )
                })}
                <Link to={convTo}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    location.pathname.startsWith('/conversations')
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'text-stone-500 hover:text-stone-700 hover:bg-stone-50'
                  }`}>
                  <MessageSquare className="h-4 w-4" />
                  <span className="hidden sm:inline">对话</span>
                </Link>
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
