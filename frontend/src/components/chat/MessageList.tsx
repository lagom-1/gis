import { useEffect, useRef } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'
import { getStepDescription } from '../../services/toolNames'
import type { Message, ToolCall, ExecutionPhase } from '../../types/conversation'

interface Props {
  messages: Message[]
  toolCalls: ToolCall[]
  phase: ExecutionPhase
  answer: string
  step?: number
  maxSteps?: number
  currentTool?: string
  reason?: string
}

export function MessageList({ messages, toolCalls, phase, answer, step, maxSteps, currentTool, reason }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls, phase, answer])

  const isActive = phase === 'thinking' || phase === 'executing'

  // 收集 SSE 实时工具名称，用于去重（SSE 工具调用和 API 持久化消息去重）
  const liveToolNames = new Set(toolCalls.map(tc => tc.tool))

  return (
    <div className="space-y-1">
      {messages.map((msg) => {
        if (msg.role === 'tool_call' || msg.role === 'tool_result') {
          // 如果 SSE 实时流中已有同名工具调用，跳过 API 持久化消息（避免重复显示）
          const msgToolName = msg.tool_name || ''
          if (msgToolName && liveToolNames.has(msgToolName)) {
            return null
          }
          const result = msg.tool_result as Record<string, unknown> | undefined
          const call: ToolCall = {
            tool: msg.tool_name || 'unknown',
            args: (msg.tool_args as Record<string, unknown>) || {},
            result: result || undefined,
            status: msg.role === 'tool_result'
              ? (result && result.success === false ? 'error' : 'success')
              : 'success',
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
                {phase === 'thinking'
                  ? '正在分析任务...'
                  : getStepDescription(step || 0, maxSteps || 0, currentTool, reason)}
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
