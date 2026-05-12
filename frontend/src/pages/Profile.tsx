import { useAuth } from '../hooks/useAuth'
import { User, Mail, Calendar, Coins } from 'lucide-react'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'

export default function Profile() {
  const { user } = useAuth()

  if (!user) {
    return <div className="text-center py-12 text-gray-500">请先登录</div>
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">个人资料</h1>
      <div className="bg-white rounded-xl p-6 border">
        <div className="space-y-4">
          <div className="flex items-center space-x-4">
            <div className="w-16 h-16 bg-primary-100 rounded-full flex items-center justify-center">
              <User className="h-8 w-8 text-primary-600" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-gray-900">{user.username}</h2>
              <p className="text-gray-500">用户 ID: {user.id}</p>
            </div>
          </div>

          <div className="border-t pt-4 space-y-3">
            <div className="flex items-center space-x-3">
              <Mail className="h-5 w-5 text-gray-400" />
              <span className="text-gray-700">{user.email}</span>
            </div>
            <div className="flex items-center space-x-3">
              <Coins className="h-5 w-5 text-gray-400" />
              <span className="text-gray-700">{user.credits} 积分</span>
            </div>
            <div className="flex items-center space-x-3">
              <Calendar className="h-5 w-5 text-gray-400" />
              <span className="text-gray-700">
                注册于 {format(new Date(user.created_at), 'yyyy-MM-dd', { locale: zhCN })}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
