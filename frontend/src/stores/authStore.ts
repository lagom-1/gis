import { create } from 'zustand'
import type { User } from '../types'
import { authService } from '../services/auth'

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => void
  fetchUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem('token'),
  isLoading: false,
  error: null,

  login: async (username, password) => {
    set({ isLoading: true, error: null })
    try {
      const { access_token } = await authService.login({ username, password })
      localStorage.setItem('token', access_token)
      set({ token: access_token })
      const user = await authService.getMe()
      set({ user, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '登录失败', isLoading: false })
      throw error
    }
  },

  register: async (username, email, password) => {
    set({ isLoading: true, error: null })
    try {
      await authService.register({ username, email, password })
      set({ isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '注册失败', isLoading: false })
      throw error
    }
  },

  logout: () => {
    localStorage.removeItem('token')
    set({ user: null, token: null })
  },

  fetchUser: async () => {
    const token = localStorage.getItem('token')
    if (!token) return
    try {
      const user = await authService.getMe()
      set({ user })
    } catch {
      localStorage.removeItem('token')
      set({ user: null, token: null })
    }
  },
}))
