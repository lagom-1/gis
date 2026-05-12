import { useState } from 'react'
import { Download } from 'lucide-react'
import PaymentModal from './PaymentModal'
import { usePayments } from '../hooks/usePayments'
import type { PricingTier } from '../types'
import toast from 'react-hot-toast'

interface DownloadButtonProps {
  taskId: number
  filename: string
  isPaid?: boolean
}

export default function DownloadButton({ taskId, filename, isPaid }: DownloadButtonProps) {
  const [showPayment, setShowPayment] = useState(false)
  const { createPayment, isLoading } = usePayments()

  const handleDownload = () => {
    if (isPaid) {
      window.open(`/api/downloads/${taskId}/${filename}`, '_blank')
    } else {
      setShowPayment(true)
    }
  }

  const handlePay = async (tier: PricingTier) => {
    try {
      await createPayment(taskId, tier)
      setShowPayment(false)
      // createPayment 会自动跳转到 Stripe 支付页面
    } catch {
      toast.error('支付失败，请重试')
    }
  }

  return (
    <>
      <button
        onClick={handleDownload}
        className="flex items-center space-x-2 bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition-colors"
      >
        <Download className="h-4 w-4" />
        <span>{isPaid ? '下载' : '付费下载'}</span>
      </button>
      <PaymentModal
        isOpen={showPayment}
        onClose={() => setShowPayment(false)}
        onPay={handlePay}
        isLoading={isLoading}
      />
    </>
  )
}
