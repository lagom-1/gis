import { useState } from 'react'
import { ChevronDown, ChevronRight, Check, X, Loader2, Settings } from 'lucide-react'
import type { ToolCall } from '../../types/conversation'

interface Props { call: ToolCall }

const STATUS = {
  running:  { icon: Loader2, color: 'text-blue-500 animate-spin', bg: 'bg-blue-50', dot: 'bg-blue-500' },
  success:  { icon: Check,    color: 'text-emerald-500', bg: 'bg-emerald-50', dot: 'bg-emerald-500' },
  error:    { icon: X,        color: 'text-red-500', bg: 'bg-red-50', dot: 'bg-red-500' },
  pending:  { icon: Settings, color: 'text-gray-400', bg: 'bg-gray-50', dot: 'bg-gray-300' },
}

export function ToolCallCard({ call }: Props) {
  const [expanded, setExpanded] = useState(false)
  const s = STATUS[call.status] || STATUS.pending
  const Icon = s.icon

  return (
    <div className="my-1">
      <button
        onClick={() => call.result && setExpanded(!expanded)}
        className={`flex items-center gap-2 w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors ${s.bg} ${call.result ? 'cursor-pointer hover:brightness-95' : ''}`}
      >
        <Icon className={`h-3 w-3 flex-shrink-0 ${s.color}`} />
        <span className="font-medium text-gray-700 flex-1 truncate">{call.tool}</span>
        {call.result && (
          <>
            <span className={`text-[10px] ${call.status === 'error' ? 'text-red-500' : 'text-gray-400'}`}>
              {call.status === 'error' ? '失败' : '完成'}
            </span>
            {expanded ? <ChevronDown className="h-3 w-3 text-gray-400" /> : <ChevronRight className="h-3 w-3 text-gray-400" />}
          </>
        )}
      </button>
      {expanded && call.result && (
        <div className="mt-1 ml-6 px-3 py-2 bg-gray-50 rounded border border-gray-100 text-xs text-gray-500 font-mono max-h-40 overflow-y-auto">
          <pre className="whitespace-pre-wrap break-all">{JSON.stringify(call.result, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}
