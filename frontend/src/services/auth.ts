import api from './api'
import type { LoginRequest, RegisterRequest, AuthResponse, User, SendCodeRequest, LoginWithCodeRequest, WechatAuthResponse } from '../types'

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

  async sendCode(data: SendCodeRequest): Promise<{ message: string }> {
    const response = await api.post('/auth/send-code', data)
    return response.data
  },

  async loginWithCode(data: LoginWithCodeRequest): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/auth/login-with-code', data)
    return response.data
  },

  async getWechatAuthUrl(): Promise<WechatAuthResponse> {
    const response = await api.get<WechatAuthResponse>('/auth/wechat')
    return response.data
  },
}
