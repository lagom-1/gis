import { create } from 'zustand'
import { authService } from '../services/auth'
import type { User, LoginRequest, RegisterRequest } from '../types'

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  login: (data: LoginRequest) => Promise<boolean>
  register: (data: RegisterRequest) => Promise<boolean>
  logout: () => void
  fetchUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: localStorage.getItem('token'),
  isLoading: false,
  error: null,

  login: async (data: LoginRequest) => {
    set({ isLoading: true, error: null })
    try {
      const res = await authService.login(data)
      const token = res.access_token
      localStorage.setItem('token', token)
      set({ token })
      // 获取用户信息
      const user = await authService.getMe()
      set({ user, isLoading: false })
      return true
    } catch (err: any) {
      const msg = err.response?.data?.detail || '登录失败'
      set({ error: msg, isLoading: false })
      return false
    }
  },

  register: async (data: RegisterRequest) => {
    set({ isLoading: true, error: null })
    try {
      await authService.register(data)
      set({ isLoading: false })
      return true
    } catch (err: any) {
      const msg = err.response?.data?.detail || '注册失败'
      set({ error: msg, isLoading: false })
      return false
    }
  },

  logout: () => {
    localStorage.removeItem('token')
    set({ user: null, token: null, error: null })
  },

  fetchUser: async () => {
    const token = get().token
    if (!token) return
    try {
      const user = await authService.getMe()
      set({ user })
    } catch {
      // token 无效
      localStorage.removeItem('token')
      set({ user: null, token: null })
    }
  },
}))
