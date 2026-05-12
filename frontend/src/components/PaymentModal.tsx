import { useState } from 'react'
import { X, Check } from 'lucide-react'
import { clsx } from 'clsx'
import type { PricingTier } from '../types'
import { PRICING_TIERS } from '../types'

interface PaymentModalProps {
  isOpen: boolean
  onClose: () => void
  onPay: (tier: PricingTier) => Promise<void>
  isLoading?: boolean
}

export default function PaymentModal({ isOpen, onClose, onPay, isLoading }: PaymentModalProps) {
  const [selectedTier, setSelectedTier] = useState<PricingTier>('basic')

  if (!isOpen) return null

  const handlePay = async () => {
    await onPay(selectedTier)
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose} />
        <div className="relative transform overflow-hidden rounded-lg bg-white px-4 pb-4 pt-5 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:p-6">
          <div className="absolute right-0 top-0 pr-4 pt-4">
            <button
              type="button"
              className="rounded-md bg-white text-gray-400 hover:text-gray-500"
              onClick={onClose}
            >
              <X className="h-6 w-6" />
            </button>
          </div>
          <div>
            <h3 className="text-lg font-semibold leading-6 text-gray-900 mb-4">
              选择下载方案
            </h3>
            <div className="space-y-3">
              {(Object.entries(PRICING_TIERS) as [PricingTier, typeof PRICING_TIERS.free][]).map(
                ([key, tier]) => (
                  <button
                    key={key}
                    onClick={() => setSelectedTier(key)}
                    className={clsx(
                      'w-full text-left p-4 rounded-lg border-2 transition-colors',
                      selectedTier === key
                        ? 'border-primary-500 bg-primary-50'
                        : 'border-gray-200 hover:border-gray-300'
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center space-x-2">
                          <span className="font-medium">{tier.label}</span>
                          <span className="text-lg font-bold text-primary-600">
                            ¥{tier.price}
                          </span>
                        </div>
                        <p className="text-sm text-gray-500 mt-1">{tier.description}</p>
                      </div>
                      {selectedTier === key && (
                        <Check className="h-5 w-5 text-primary-600" />
                      )}
                    </div>
                  </button>
                )
              )}
            </div>
          </div>
          <div className="mt-5 sm:mt-6">
            <button
              type="button"
              disabled={isLoading}
              onClick={handlePay}
              className="w-full bg-primary-600 text-white py-3 px-4 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? '处理中...' : `支付 ¥${PRICING_TIERS[selectedTier].price}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
