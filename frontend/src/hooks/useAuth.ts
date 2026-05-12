import type { User } from '../types'

const dummyUser: User = {
  id: 0,
  username: 'guest',
  email: 'guest@opengis.local',
  credits: 9999,
  created_at: new Date().toISOString(),
}

export function useAuth() {
  return {
    user: dummyUser,
    isAuthenticated: true,
    isLoading: false,
    error: null,
    login: async () => {},
    register: async () => {},
    logout: () => {},
  }
}
