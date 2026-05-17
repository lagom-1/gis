import { useEffect, useState, useRef } from 'react'
import TaskCard from '../components/TaskCard'
import LoadingSpinner from '../components/LoadingSpinner'
import { useTaskStore } from '../stores/taskStore'
import { clsx } from 'clsx'

const statusFilters = [
  { value: '', label: '全部' },
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

export default function Dashboard() {
  const { tasks, isLoading, fetchTasks } = useTaskStore()
  const [statusFilter, setStatusFilter] = useState('')
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetchTasks({ status: statusFilter || undefined })
  }, [fetchTasks, statusFilter])

  // 有运行中的任务时自动刷新
  useEffect(() => {
    const hasRunning = tasks.some(t => t.status === 'running' || t.status === 'pending')
    if (hasRunning && !pollTimerRef.current) {
      pollTimerRef.current = setInterval(() => {
        fetchTasks({ status: statusFilter || undefined }, true)  // 静默刷新，不显示 loading
      }, 5000)
    } else if (!hasRunning && pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [tasks, fetchTasks, statusFilter])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">任务列表</h1>
      </div>

      <div className="flex space-x-2">
        {statusFilters.map((filter) => (
          <button
            key={filter.value}
            onClick={() => setStatusFilter(filter.value)}
            className={clsx(
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              statusFilter === filter.value
                ? 'bg-primary-600 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-100 border'
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="py-12">
          <LoadingSpinner size="lg" />
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-12 text-gray-500">暂无任务</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {tasks.map((task) => (
            <TaskCard key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  )
}
