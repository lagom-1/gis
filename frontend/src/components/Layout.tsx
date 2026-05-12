import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { LogOut, Map, User, MessageSquare } from 'lucide-react'

export default function Layout() {
  const { user, isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    logout()
    navigate('/')
  }

  const isWorkspace = location.pathname === '/workspace'

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <Link to="/" className="flex items-center space-x-2">
                <Map className="h-8 w-8 text-primary-600" />
                <span className="text-xl font-bold text-gray-900">OpenGIS</span>
              </Link>
              {isAuthenticated && (
                <div className="ml-10 flex items-baseline space-x-4">
                  <Link
                    to="/workspace"
                    className={`flex items-center space-x-1 px-3 py-2 rounded-md text-sm font-medium ${
                      isWorkspace
                        ? 'bg-primary-100 text-primary-700'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    <MessageSquare className="h-4 w-4" />
                    <span>工作空间</span>
                  </Link>
                  <Link
                    to="/dashboard"
                    className="text-gray-600 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium"
                  >
                    任务列表
                  </Link>
                  <Link
                    to="/submit"
                    className="text-gray-600 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium"
                  >
                    新建任务
                  </Link>
                </div>
              )}
            </div>
            <div className="flex items-center">
              {isAuthenticated ? (
                <div className="flex items-center space-x-4">
                  <Link
                    to="/profile"
                    className="flex items-center space-x-2 text-gray-600 hover:text-gray-900"
                  >
                    <User className="h-5 w-5" />
                    <span className="text-sm">{user?.username}</span>
                    <span className="text-xs text-gray-500">({user?.credits} 积分)</span>
                  </Link>
                  <button
                    onClick={handleLogout}
                    className="flex items-center space-x-2 text-gray-600 hover:text-gray-900"
                  >
                    <LogOut className="h-5 w-5" />
                    <span className="text-sm">退出</span>
                  </button>
                </div>
              ) : (
                <div className="flex items-center space-x-4">
                  <Link
                    to="/login"
                    className="text-gray-600 hover:text-gray-900 px-3 py-2 rounded-md text-sm font-medium"
                  >
                    登录
                  </Link>
                  <Link
                    to="/register"
                    className="bg-primary-600 text-white hover:bg-primary-700 px-4 py-2 rounded-md text-sm font-medium"
                  >
                    注册
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>
      </nav>
      <main className={isWorkspace ? 'overflow-hidden' : 'max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8'}>
        <Outlet />
      </main>
    </div>
  )
}
