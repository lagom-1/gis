import { useState } from 'react'
import { paymentsService, type PaymentCreateResponse } from '../services/payments'
import type { Order, PricingTier } from '../types'

export function usePayments() {
  const [order, setOrder] = useState<Order | null>(null)
  const [paymentResult, setPaymentResult] = useState<PaymentCreateResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * 创建支付订单并跳转到支付页面
   */
  const createPayment = async (taskId: number, tier: PricingTier) => {
    setIsLoading(true)
    setError(null)
    try {
      const result = await paymentsService.createPayment({ task_id: taskId, tier })
      setPaymentResult(result)
      setIsLoading(false)

      // 如果有支付链接，跳转到 Stripe 支付页面
      if (result.checkout_url) {
        window.location.href = result.checkout_url
      }

      return result
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建支付订单失败')
      setIsLoading(false)
      throw err
    }
  }

  /**
   * 查询订单状态
   */
  const checkOrder = async (orderId: number) => {
    try {
      const updatedOrder = await paymentsService.getOrder(orderId)
      setOrder(updatedOrder)
      return updatedOrder
    } catch (err: any) {
      setError(err.response?.data?.detail || '查询订单状态失败')
      throw err
    }
  }

  /**
   * 取消待支付订单
   */
  const cancelOrder = async (orderId: number) => {
    try {
      const result = await paymentsService.cancelOrder(orderId)
      if (result.success) {
        setOrder(null)
        setPaymentResult(null)
      }
      return result
    } catch (err: any) {
      setError(err.response?.data?.detail || '取消订单失败')
      throw err
    }
  }

  return {
    order,
    paymentResult,
    isLoading,
    error,
    createPayment,
    checkOrder,
    cancelOrder,
  }
}
