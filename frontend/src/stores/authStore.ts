import { create } from 'zustand'
import type { User } from '../types'

const dummyUser: User = {
  id: 0,
  username: 'guest',
  email: 'guest@opengis.local',
  credits: 9999,
  created_at: new Date().toISOString(),
}

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  login: () => Promise<void>
  register: () => Promise<void>
  logout: () => void
  fetchUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: dummyUser,
  token: 'dummy-token',
  isLoading: false,
  error: null,

  login: async () => {
    set({ user: dummyUser, token: 'dummy-token' })
  },

  register: async () => {
    set({ user: dummyUser, token: 'dummy-token' })
  },

  logout: () => {
    set({ user: dummyUser, token: 'dummy-token' })
  },

  fetchUser: async () => {
    set({ user: dummyUser })
  },
}))
