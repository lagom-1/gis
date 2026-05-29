import { useState, useEffect } from 'react'
import { X, Copy, Check, Loader2 } from 'lucide-react'
import api from '../services/api'

interface PaymentModalProps {
  isOpen: boolean
  onClose: () => void
  taskId?: number
  filePath?: string
  onDownload: () => void
}

interface PermissionData {
  can_download: boolean
  download_type: string | null
  share_remaining: number
  price_yuan: number
  payment_status: string | null
  task_id?: number
}

export default function PaymentModal({ isOpen, onClose, taskId, filePath, onDownload }: PaymentModalProps) {
  const [permission, setPermission] = useState<PermissionData | null>(null)
  const [copied, setCopied] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState('')
  const [paymentId, setPaymentId] = useState<number | null>(null)

  const githubUrl = 'https://github.com/lagom-1/gis/tree/master'

  useEffect(() => {
    if (isOpen) {
      checkPermission()
    }
  }, [isOpen, taskId, filePath])

  const checkPermission = async () => {
    try {
      let res
      if (taskId) {
        res = await api.get(`/downloads/${taskId}/check-permission`)
      } else if (filePath) {
        res = await api.get(`/downloads/by-path`, { params: { file_path: filePath } })
      }
      if (res) {
        setPermission(res.data)
      }
    } catch {
      setError('检查权限失败')
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(githubUrl)
      setCopied(true)
    } catch {
      const input = document.createElement('input')
      input.value = githubUrl
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
      setCopied(true)
    }
  }

  const handleShare = async () => {
    setIsProcessing(true)
    setError('')
    try {
      if (taskId) {
        await api.post(`/downloads/${taskId}/share`)
      } else if (filePath) {
        await api.post(`/downloads/by-path/share`, null, { params: { file_path: filePath } })
      }
      onDownload()
      onClose()
    } catch (err: any) {
      setError(err.response?.data?.detail || '分享失败')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleCreatePayment = async () => {
    setIsProcessing(true)
    setError('')
    try {
      let res
      if (taskId) {
        res = await api.post(`/downloads/${taskId}/payment`)
      } else if (filePath) {
        res = await api.post(`/downloads/by-path/payment`, null, { params: { file_path: filePath } })
      }
      if (res) {
        setPaymentId(res.data.payment_id)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建支付失败')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleConfirmPayment = async () => {
    if (!paymentId) return
    setIsProcessing(true)
    setError('')
    try {
      await api.post('/downloads/confirm-payment', { payment_id: paymentId })
      onDownload()
      onClose()
    } catch (err: any) {
      setError(err.response?.data?.detail || '确认失败，请稍后再试')
    } finally {
      setIsProcessing(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full mx-4 overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-stone-900">下载文件</h3>
          <button onClick={onClose} className="text-stone-400 hover:text-stone-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex flex-col md:flex-row">
          {/* 左侧：分享免费下载 */}
          <div className="flex-1 p-6 border-r border-stone-200">
            <div className="text-center">
              <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">🔗</span>
              </div>
              <h4 className="font-semibold text-stone-900 mb-2">分享免费下载</h4>
              <p className="text-sm text-stone-500 mb-6">
                分享 OpenGIS 项目到 GitHub<br />
                即可免费下载 1 次
              </p>

              {/* GitHub 链接 */}
              <div className="bg-stone-50 rounded-lg p-3 mb-4">
                <div className="text-xs text-stone-400 mb-2">项目链接</div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={githubUrl}
                    readOnly
                    className="flex-1 px-3 py-2 border border-stone-200 rounded-md text-xs bg-white"
                  />
                  <button
                    onClick={handleCopy}
                    className="px-3 py-2 bg-emerald-600 text-white rounded-md text-xs hover:bg-emerald-700 transition"
                  >
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* 我已分享按钮 */}
              <button
                onClick={handleShare}
                disabled={!copied || isProcessing || permission?.download_type !== 'share'}
                className="w-full py-2.5 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
              >
                {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {isProcessing ? '处理中...' : '✓ 我已分享，下载文件'}
              </button>

              <div className="text-xs text-stone-400 mt-3">
                本周剩余 {permission?.share_remaining ?? 3}/3 次免费下载
              </div>
            </div>
          </div>

          {/* 右侧：付费下载 */}
          <div className="flex-1 p-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-amber-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">💰</span>
              </div>
              <h4 className="font-semibold text-stone-900 mb-2">付费下载</h4>
              <p className="text-sm text-stone-500 mb-6">
                扫码支付后即可下载<br />
                支持微信支付
              </p>

              {/* 价格显示 */}
              <div className="bg-amber-50 rounded-lg p-4 mb-4">
                <div className="text-xs text-amber-700 mb-1">本次下载费用</div>
                <div className="text-3xl font-bold text-amber-600">
                  ¥{permission?.price_yuan?.toFixed(2) ?? '1.00'}
                </div>
              </div>

              {/* 微信收款码 */}
              <div className="bg-stone-50 rounded-lg p-4 mb-4">
                <div className="text-xs text-stone-400 mb-3">微信扫码支付</div>
                <div className="w-32 h-32 bg-white border border-stone-200 rounded-lg mx-auto overflow-hidden">
                  <img
                    src="/qrcode.jpg"
                    alt="微信收款码"
                    className="w-full h-full object-contain"
                  />
                </div>
              </div>

              {/* 按钮区域 */}
              {!paymentId ? (
                <button
                  onClick={handleCreatePayment}
                  disabled={isProcessing}
                  className="w-full py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
                >
                  {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {isProcessing ? '处理中...' : '我已支付，下载文件'}
                </button>
              ) : (
                <button
                  onClick={handleConfirmPayment}
                  disabled={isProcessing}
                  className="w-full py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
                >
                  {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {isProcessing ? '确认中...' : '✓ 我已支付，确认下载'}
                </button>
              )}

              <div className="text-xs text-stone-400 mt-3">
                支付后请稍等片刻，系统将自动确认
              </div>
            </div>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-t border-red-100">
            <p className="text-sm text-red-600 text-center">{error}</p>
          </div>
        )}
      </div>
    </div>
  )
}
