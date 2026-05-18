import { useEffect, useRef, useCallback } from 'react'
import { useConversation } from '../../hooks/useConversation'
import { ChatInput } from './ChatInput'
import { MessageList } from './MessageList'
import { ExamplePrompts } from './ExamplePrompts'
import type { Message, ToolCall } from '../../types/conversation'

interface Props {
  convId: number | null
  messages: Message[]
  onNewMessage: (msg: Message) => void
  onToolResult?: (call: ToolCall) => void
  onSendStart?: () => void
}

export function ChatPanel({ convId, messages, onNewMessage, onToolResult, onSendStart }: Props) {
  const { phase, toolCalls, answer, send } = useConversation()
  const prevPhaseRef = useRef(phase)
  const prevAnswerRef = useRef(answer)
  const prevToolCallsLenRef = useRef(0)

  useEffect(() => {
    const wasNotDone = prevPhaseRef.current !== 'done'
    const isNowDone = phase === 'done'
    const hasNewAnswer = answer && answer !== prevAnswerRef.current
    if (isNowDone && wasNotDone && hasNewAnswer) {
      onNewMessage({
        id: Date.now(),
        conversation_id: convId ?? 0,
        role: 'assistant',
        content: answer,
        created_at: new Date().toISOString(),
      })
    }
    prevPhaseRef.current = phase
    prevAnswerRef.current = answer
  }, [phase, answer, convId, onNewMessage])

  useEffect(() => {
    if (toolCalls.length > prevToolCallsLenRef.current && onToolResult) {
      toolCalls.slice(prevToolCallsLenRef.current).forEach(call => {
        if (call.status === 'success' || call.status === 'error') onToolResult(call)
      })
    }
    prevToolCallsLenRef.current = toolCalls.length
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

  const statusDot = phase === 'thinking' || phase === 'executing' ? 'bg-amber-500 animate-pulse' :
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
        <span className="text-xs text-gray-400">{messages.length} 条消息</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="text-center pt-10 pb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-1">GIS 遥感智能助手</h2>
            <p className="text-sm text-gray-400">输入自然语言指令，自动完成遥感分析</p>
          </div>
        )}
        <MessageList messages={messages} toolCalls={toolCalls} phase={phase} answer={answer} />
        <ExamplePrompts onSelect={handleSend} />
      </div>

      <ChatInput onSend={handleSend} disabled={phase === 'thinking' || phase === 'executing'} />
    </div>
  )
}
