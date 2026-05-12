import { Link } from 'react-router-dom'
import { format } from 'date-fns'
import { zhCN } from 'date-fns/locale'
import StatusBadge from './StatusBadge'
import type { Task } from '../types'

interface TaskCardProps {
  task: Task
}

export default function TaskCard({ task }: TaskCardProps) {
  return (
    <Link
      to={`/tasks/${task.id}`}
      className="block bg-white rounded-lg shadow-sm border hover:shadow-md transition-shadow p-4"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="text-lg font-medium text-gray-900 line-clamp-2 flex-1 mr-4">
          {task.input_text}
        </h3>
        <StatusBadge status={task.status} />
      </div>
      <div className="flex items-center text-sm text-gray-500 space-x-4">
        <span>
          {format(new Date(task.created_at), 'yyyy-MM-dd HH:mm', { locale: zhCN })}
        </span>
        {task.completed_at && (
          <span>
            完成于 {format(new Date(task.completed_at), 'HH:mm', { locale: zhCN })}
          </span>
        )}
      </div>
      {task.error_message && (
        <p className="mt-2 text-sm text-red-600 line-clamp-1">{task.error_message}</p>
      )}
    </Link>
  )
}
