import { clsx } from 'clsx'

interface StatusBadgeProps {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
}

const statusConfig = {
  pending: { label: '等待中', className: 'bg-yellow-100 text-yellow-800' },
  running: { label: '运行中', className: 'bg-blue-100 text-blue-800' },
  completed: { label: '已完成', className: 'bg-green-100 text-green-800' },
  failed: { label: '失败', className: 'bg-red-100 text-red-800' },
  cancelled: { label: '已取消', className: 'bg-gray-100 text-gray-800' },
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status]

  return (
    <span
      className={clsx(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
        config.className
      )}
    >
      {config.label}
    </span>
  )
}
