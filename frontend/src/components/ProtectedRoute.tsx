import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAppStore } from '../stores/appStore'
import { authService } from '../services/auth'

/**
 * 路由守卫
 * 每次访问都验证 token 有效性
 */
export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAppStore((s) => s.token)
  const setUser = useAppStore((s) => s.setUser)
  const logout = useAppStore((s) => s.logout)
  const [checking, setChecking] = useState(true)
  const [valid, setValid] = useState(false)

  useEffect(() => {
    const checkAuth = async () => {
      if (!token) {
        setValid(false)
        setChecking(false)
        return
      }

      // 直接调用 API 验证 token
      try {
        const user = await authService.getMe()
        setUser(user)
        setValid(true)
      } catch {
        // token 无效，清除登录状态
        logout()
        setValid(false)
      } finally {
        setChecking(false)
      }
    }

    checkAuth()
  }, []) // 只在组件挂载时检查一次

  // 检查中显示加载状态
  if (checking) {
    return (
      <div className="min-h-screen bg-stone-50 flex items-center justify-center">
        <div className="text-stone-500">验证登录状态...</div>
      </div>
    )
  }

  // 未登录跳转到登录页面
  if (!valid || !token) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
