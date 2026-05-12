import api from './api'
import type { LoginRequest, RegisterRequest, AuthResponse, User } from '../types'

export const authService = {
  async login(data: LoginRequest): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/auth/login', data)
    return response.data
  },

  async register(data: RegisterRequest): Promise<User> {
    const response = await api.post<User>('/auth/register', data)
    return response.data
  },

  async getMe(): Promise<User> {
    const response = await api.get<User>('/auth/me')
    return response.data
  },
}
