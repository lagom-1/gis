import { useEffect, useRef, useCallback } from 'react'
import { useConversation } from '../../hooks/useConversation'
import { ChatInput } from './ChatInput'
import { MessageList } from './MessageList'
import { ExamplePrompts } from './ExamplePrompts'
import { XCircle } from 'lucide-react'
import type { Message, ToolCall } from '../../types/conversation'

interface Props {
  convId: number | null
  messages: Message[]
  onNewMessage: (msg: Message) => void
  onToolResult?: (call: ToolCall) => void
  onSendStart?: () => void
  onCancel?: () => void
  hideTools?: boolean
}

export function ChatPanel({ convId, messages, onNewMessage, onToolResult, onSendStart, onCancel, hideTools }: Props) {
  const { phase, toolCalls, answer, send, abort } = useConversation()
  const prevPhaseRef = useRef(phase)
  const prevAnswerRef = useRef(answer)
  const notifiedCountRef = useRef(0)

  useEffect(() => {
    const wasNotDone = prevPhaseRef.current !== 'done'
    const isNowDone = phase === 'done'
    if (isNowDone && wasNotDone) {
      const content = answer || '任务已完成。'
      onNewMessage({
        id: Date.now(),
        conversation_id: convId ?? 0,
        role: 'assistant',
        content,
        created_at: new Date().toISOString(),
      })
    }
    prevPhaseRef.current = phase
    prevAnswerRef.current = answer
  }, [phase, answer, convId, onNewMessage])

  useEffect(() => {
    if (!onToolResult) return
    const completed = toolCalls.filter(call => call.status === 'success' || call.status === 'error')
    if (completed.length > notifiedCountRef.current) {
      completed.slice(notifiedCountRef.current).forEach(call => {
        onToolResult(call)
      })
    }
    notifiedCountRef.current = completed.length
  }, [toolCalls, onToolResult])

  const handleSend = useCallback(async (content: string) => {
    if (!convId) return
    onNewMessage({
      id: Date.now(), conversation_id: convId,
      role: 'user', content, created_at: new Date().toISOString(),
    })
    onSendStart?.()
    await send(convId, content)
  }, [convId, onNewMessage, onSendStart, send])

  const handleCancel = useCallback(() => {
    abort()
    onCancel?.()
  }, [abort, onCancel])

  const isRunning = phase === 'thinking' || phase === 'executing'
  const statusDot = isRunning ? 'bg-amber-500 animate-pulse' :
    phase === 'done' ? 'bg-emerald-500' : phase === 'waiting_for_user' ? 'bg-amber-500' : 'bg-gray-300'

  const statusText = phase === 'thinking' ? '分析中' : phase === 'executing' ? '执行中' :
    phase === 'waiting_for_user' ? '等待输入' : phase === 'done' ? '完成' : '就绪'

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${statusDot}`} />
          <span className="text-xs text-gray-500 font-medium">{statusText}</span>
        </div>
        <div className="flex items-center gap-2">
          {isRunning && (
            <button
              onClick={handleCancel}
              className="flex items-center gap-1 px-2.5 py-1 text-xs text-red-600 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
            >
              <XCircle className="h-3.5 w-3.5" />
              取消
            </button>
          )}
          <span className="text-xs text-gray-400">{messages.length} 条消息</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="text-center pt-10 pb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-1">GIS 遥感智能助手</h2>
            <p className="text-sm text-gray-400">输入自然语言指令，自动完成遥感分析</p>
          </div>
        )}
        <MessageList
          messages={messages}
          toolCalls={toolCalls}
          phase={phase}
          answer={answer}
          step={toolCalls.length > 0 ? toolCalls.filter(tc => tc.status !== 'running').length + 1 : 0}
          maxSteps={undefined}
          currentTool={toolCalls[toolCalls.length - 1]?.tool}
          reason={toolCalls[toolCalls.length - 1]?.reason}
          hideTools={hideTools}
        />
        <ExamplePrompts onSelect={handleSend} />
      </div>

      <ChatInput onSend={handleSend} disabled={isRunning} />
    </div>
  )
}
