import api from './api'
import type { Order, PaymentCreateRequest } from '../types'

export interface PaymentCreateResponse {
  order_id: number
  checkout_url: string | null
  session_id: string | null
  amount_cents: number
  currency: string
  message: string | null
}

export interface PricingTier {
  name: string
  price_cents: number
  currency: string
  description: string
  includes: string[]
}

export interface TiersResponse {
  tiers: PricingTier[]
}

export const paymentsService = {
  /**
   * 创建支付订单
   * 返回支付链接，前端跳转到 Stripe 支付页面
   */
  async createPayment(data: PaymentCreateRequest): Promise<PaymentCreateResponse> {
    const response = await api.post<PaymentCreateResponse>('/payments/create', data)
    return response.data
  },

  /**
   * 查询订单状态
   */
  async getOrder(orderId: number): Promise<Order> {
    const response = await api.get<Order>(`/payments/${orderId}`)
    return response.data
  },

  /**
   * 获取定价层级信息
   */
  async getTiers(): Promise<TiersResponse> {
    const response = await api.get<TiersResponse>('/payments/tiers')
    return response.data
  },

  /**
   * 取消待支付订单
   */
  async cancelOrder(orderId: number): Promise<{ success: boolean; message: string }> {
    const response = await api.post(`/payments/cancel/${orderId}`)
    return response.data
  },

  /**
   * 查询任务关联的订单列表
   */
  async getOrdersByTask(taskId: number): Promise<Order[]> {
    const response = await api.get<Order[]>(`/payments/task/${taskId}`)
    return response.data
  },
}
