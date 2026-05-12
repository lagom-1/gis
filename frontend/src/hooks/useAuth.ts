import { useEffect } from 'react'
import { useAuthStore } from '../stores/authStore'

export function useAuth() {
  const { user, token, isLoading, error, login, register, logout, fetchUser } = useAuthStore()

  useEffect(() => {
    if (token && !user) {
      fetchUser()
    }
  }, [token, user, fetchUser])

  // 只要 token 存在就认为已认证，不依赖 user 是否加载完成
  return {
    user,
    isAuthenticated: !!token,
    isLoading,
    error,
    login,
    register,
    logout,
  }
}
