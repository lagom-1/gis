import { useEffect, useRef } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
import { MessageBubble } from './MessageBubble'
import type { Message, ToolCall, ExecutionPhase } from '../../types/conversation'

interface Props {
  messages: Message[]
  toolCalls: ToolCall[]
  phase: ExecutionPhase
  answer: string
  hideTools?: boolean
}

export function MessageList({ messages, toolCalls, phase, answer, hideTools }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls, phase, answer])

  const isStreaming = phase === 'thinking' || phase === 'executing'

  return (
    <div className="space-y-1">
      {messages.map((msg) => {
        if (msg.role === 'tool_call' || msg.role === 'tool_result') {
          // 工具步骤消息永远不渲染，只显示 assistant 最终总结
          return null
        }
        return (
          <MessageBubble key={`${msg.id}-${msg.role}`} role={msg.role} content={msg.content} timestamp={msg.created_at} hideTools={hideTools} />
        )
      })}

      {isStreaming && (
        <div className="flex justify-start">
          <div className="bg-amber-50 border border-amber-100 rounded-2xl rounded-bl-md px-4 py-3">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
              <span className="text-sm text-amber-700 font-medium">
                {phase === 'thinking' ? '正在分析任务...' : '正在执行中...'}
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
