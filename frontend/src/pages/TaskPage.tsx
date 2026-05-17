import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import { ArrowLeft, RefreshCw, XCircle } from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import OutputPreview from '../components/OutputPreview'
import LoadingSpinner from '../components/LoadingSpinner'
import { useTaskStore } from '../stores/taskStore'
import toast from 'react-hot-toast'

export default function TaskPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { currentTask, isLoading, fetchTask, cancelTask } = useTaskStore()

  useEffect(() => {
    if (id) {
      fetchTask(parseInt(id))
    }
  }, [id, fetchTask])

  // 离开任务详情页时清理 currentTask，防止泄漏到工作区
  useEffect(() => {
    return () => {
      useTaskStore.setState({ currentTask: null })
    }
  }, [])

  useEffect(() => {
    if (currentTask?.status === 'running' || currentTask?.status === 'pending') {
      const interval = setInterval(() => {
        fetchTask(currentTask.id, true)
      }, 5000)
      return () => clearInterval(interval)
    }
  }, [currentTask?.id, currentTask?.status, fetchTask])

  const handleCancel = async () => {
    if (currentTask) {
      await cancelTask(currentTask.id)
      toast.success('任务已取消')
    }
  }

  if (isLoading) {
    return (
      <div className="py-12">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (!currentTask) {
    return <div className="text-center py-12 text-gray-500">任务不存在</div>
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center space-x-2 text-gray-600 hover:text-gray-900"
        >
          <ArrowLeft className="h-5 w-5" />
          <span>返回列表</span>
        </button>
        <div className="flex items-center space-x-4">
          {(currentTask.status === 'running' || currentTask.status === 'pending') && (
            <>
              <button
                onClick={() => fetchTask(currentTask.id)}
                className="flex items-center space-x-2 text-primary-600 hover:text-primary-700"
              >
                <RefreshCw className="h-4 w-4" />
                <span>刷新</span>
              </button>
              <button
                onClick={handleCancel}
                className="flex items-center space-x-2 text-red-600 hover:text-red-700"
              >
                <XCircle className="h-4 w-4" />
                <span>取消</span>
              </button>
            </>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl p-6 border">
        <div className="flex items-start justify-between mb-4">
          <h1 className="text-xl font-bold text-gray-900 flex-1 mr-4">
            {currentTask.input_text}
          </h1>
          <StatusBadge status={currentTask.status} />
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm text-gray-600">
          <div>
            <span className="font-medium">创建时间：</span>
            {format(new Date(currentTask.created_at), 'yyyy-MM-dd HH:mm:ss', { locale: zhCN })}
          </div>
          {currentTask.started_at && (
            <div>
              <span className="font-medium">开始时间：</span>
              {format(new Date(currentTask.started_at), 'yyyy-MM-dd HH:mm:ss', { locale: zhCN })}
            </div>
          )}
          {currentTask.completed_at && (
            <div>
              <span className="font-medium">完成时间：</span>
              {format(new Date(currentTask.completed_at), 'yyyy-MM-dd HH:mm:ss', { locale: zhCN })}
            </div>
          )}
        </div>

        {currentTask.error_message && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-600">{currentTask.error_message}</p>
          </div>
        )}
      </div>

      {currentTask.status === 'completed' && (
        <div className="bg-white rounded-xl p-6 border space-y-4">
          <OutputPreview files={currentTask.output_files} taskId={currentTask.id} />
        </div>
      )}

      {(currentTask.status === 'running' || currentTask.status === 'pending') && (
        <div className="bg-white rounded-xl p-6 border text-center">
          <LoadingSpinner size="lg" />
          <p className="mt-4 text-gray-600">
            {currentTask.status === 'pending' ? '任务等待中...' : '任务执行中...'}
          </p>
          <p className="text-sm text-gray-500 mt-2">页面每 5 秒自动刷新</p>
        </div>
      )}
    </div>
  )
}
