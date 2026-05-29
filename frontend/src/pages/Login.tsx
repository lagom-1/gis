import { Navigate } from 'react-router-dom'
import { useAppStore } from '../stores/appStore'
import BrandPanel from '../components/auth/BrandPanel'
import LoginForm from '../components/auth/LoginForm'

/**
 * 登录页面
 * 左右分栏布局：左侧品牌展示 + 右侧登录表单
 * 已登录用户自动跳转到主页
 */
export default function Login() {
  const token = useAppStore((s) => s.token)

  // 已登录则跳转到主页
  if (token) {
    return <Navigate to="/gallery" replace />
  }

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col lg:flex-row animate-in fade-in duration-300">
      <BrandPanel />
      <div className="flex-1 flex items-center justify-center p-6">
        <LoginForm />
      </div>
    </div>
  )
}
