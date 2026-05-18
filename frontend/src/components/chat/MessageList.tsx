import { useEffect, useRef } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'
import type { Message, ToolCall, ExecutionPhase } from '../../types/conversation'

interface Props {
  messages: Message[]
  toolCalls: ToolCall[]
  phase: ExecutionPhase
  answer: string
}

export function MessageList({ messages, toolCalls, phase, answer }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls, phase, answer])

  const isActive = phase === 'thinking' || phase === 'executing'

  return (
    <div className="space-y-1">
      {messages.map((msg) => {
        if (msg.role === 'tool_call' || msg.role === 'tool_result') {
          const call: ToolCall = {
            tool: msg.tool_name || 'unknown',
            args: (msg.tool_args as Record<string, unknown>) || {},
            result: (msg.tool_result as Record<string, unknown>) || undefined,
            status: msg.role === 'tool_call' ? 'running' :
              msg.tool_result && (msg.tool_result as Record<string, unknown>).success === false ? 'error' : 'success',
          }
          return <ToolCallCard key={`${msg.id}-${msg.role}`} call={call} />
        }
        return (
          <MessageBubble key={`${msg.id}-${msg.role}`} role={msg.role} content={msg.content} timestamp={msg.created_at} />
        )
      })}

      {toolCalls.map((tc, i) => (
        <ToolCallCard key={`live-${tc.tool}-${i}`} call={tc} />
      ))}

      {isActive && (
        <div className="flex justify-start">
          <div className="bg-amber-50 border border-amber-100 rounded-2xl rounded-bl-md px-4 py-3">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
              <span className="text-sm text-amber-700 font-medium">
                {phase === 'thinking' ? '正在分析任务...' : '正在执行工具...'}
              </span>
            </div>
          </div>
        </div>
      )}

      {phase === 'waiting_for_user' && (
        <div className="flex justify-start">
          <div className="bg-blue-50 border border-blue-100 rounded-2xl rounded-bl-md px-4 py-3 max-w-[85%]">
            <p className="text-sm text-blue-700">{answer || '请提供更多信息...'}</p>
          </div>
        </div>
      )}

      {phase === 'done' && answer && answer.startsWith('连接错误') && messages.length <= 1 && (
        <div className="flex justify-start">
          <div className="bg-red-50 border border-red-100 rounded-2xl rounded-bl-md px-4 py-3">
            <div className="flex items-center gap-2 mb-1">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <span className="text-sm font-medium text-red-600">连接失败</span>
            </div>
            <p className="text-sm text-red-500">{answer}</p>
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  )
}
