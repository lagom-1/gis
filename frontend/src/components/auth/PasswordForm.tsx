import { useState, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'

interface PasswordFormProps {
  onSubmit: (username: string, password: string) => Promise<void>
  isLoading: boolean
  error: string
}

/**
 * 密码登录表单
 */
export default function PasswordForm({ onSubmit, isLoading, error }: PasswordFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const canSubmit = username.trim() && password.trim() && !isLoading

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (canSubmit) onSubmit(username.trim(), password)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          邮箱地址
        </label>
        <input
          type="email"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="请输入邮箱"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
          autoFocus
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="block text-sm font-medium text-stone-700">密码</label>
          <button type="button" className="text-xs text-emerald-600 hover:underline">
            忘记密码？
          </button>
        </div>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="请输入密码"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
        />
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
