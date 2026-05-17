import { useAuthStore } from '../stores/authStore'

export function useAuth() {
  const store = useAuthStore()
  return {
    user: store.user,
    isAuthenticated: !!store.token,
    isLoading: store.isLoading,
    error: store.error,
    login: store.login,
    register: store.register,
    logout: store.logout,
  }
}
