import { useState, useEffect, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'
import { authService } from '../../services/auth'

interface CodeFormProps {
  onSubmit: (email: string, code: string) => Promise<void>
  isLoading: boolean
  error: string
}

/**
 * 验证码登录表单
 */
export default function CodeForm({ onSubmit, isLoading, error }: CodeFormProps) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendLoading, setSendLoading] = useState(false)
  const [sendError, setSendError] = useState('')

  const canSubmit = email.trim() && code.trim() && !isLoading
  const canSendCode = email.trim() && countdown === 0 && !sendLoading

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown(countdown - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  const handleSendCode = async () => {
    if (!canSendCode) return
    setSendLoading(true)
    setSendError('')
    try {
      await authService.sendCode({ email: email.trim() })
      setCountdown(60)
    } catch {
      setSendError('发送失败，请检查邮箱')
    } finally {
      setSendLoading(false)
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (canSubmit) onSubmit(email.trim(), code.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          邮箱地址
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="请输入邮箱"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
          autoFocus
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          验证码
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="请输入 6 位验证码"
            maxLength={6}
            className="flex-1 px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                       focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                       outline-none transition"
          />
          <button
            type="button"
            onClick={handleSendCode}
            disabled={!canSendCode}
            className="px-4 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium
                       hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed
                       transition whitespace-nowrap"
          >
            {sendLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : countdown > 0 ? (
              `${countdown}s`
            ) : (
              '发送验证码'
            )}
          </button>
        </div>
        {sendError && (
          <p className="text-red-500 text-xs mt-1">{sendError}</p>
        )}
      </div>

      {error && (
        <div className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-2.5">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium
                   hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed
                   transition flex items-center justify-center gap-2"
      >
        {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
        {isLoading ? '登录中...' : '登录'}
      </button>
    </form>
  )
}
