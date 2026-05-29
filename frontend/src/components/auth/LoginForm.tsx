import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppStore } from '../../stores/appStore'
import TabSwitcher from './TabSwitcher'
import PasswordForm from './PasswordForm'
import CodeForm from './CodeForm'
import ThirdPartyLogin from './ThirdPartyLogin'

type LoginTab = 'password' | 'code'

/**
 * 登录表单区域
 * 整合密码登录、验证码登录、第三方登录
 */
export default function LoginForm() {
  const navigate = useNavigate()
  const login = useAppStore((s) => s.login)

  const [activeTab, setActiveTab] = useState<LoginTab>('password')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const handlePasswordLogin = async (username: string, password: string) => {
    setIsLoading(true)
    setError('')
    const ok = await login(username, password)
    setIsLoading(false)
    if (ok) {
      navigate('/gallery')
    } else {
      setError('登录失败，请检查邮箱和密码')
    }
  }

  const handleCodeLogin = async (email: string, code: string) => {
    setIsLoading(true)
    setError('')
    try {
      const { authService } = await import('../../services/auth')
      const res = await authService.loginWithCode({ email, code })
      localStorage.setItem('token', res.access_token)
      window.location.href = '/gallery'
    } catch {
      setError('验证码无效或已过期')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex flex-col justify-center px-8 sm:px-12 lg:px-16 py-12">
      <div className="w-full max-w-sm mx-auto">
        <h2 className="text-2xl font-semibold text-stone-900 mb-1">欢迎回来</h2>
        <p className="text-sm text-stone-500 mb-8">登录以继续使用 OpenGIS</p>

        <TabSwitcher activeTab={activeTab} onTabChange={setActiveTab} />

        {activeTab === 'password' ? (
          <PasswordForm
            onSubmit={handlePasswordLogin}
            isLoading={isLoading}
            error={error}
          />
        ) : (
          <CodeForm
            onSubmit={handleCodeLogin}
            isLoading={isLoading}
            error={error}
          />
        )}

        <ThirdPartyLogin />

        <p className="text-center text-sm text-stone-500 mt-8">
          还没有账号？{' '}
          <Link
            to="/register"
            className="text-emerald-600 hover:underline font-medium"
          >
            立即注册
          </Link>
        </p>
      </div>
    </div>
  )
}
