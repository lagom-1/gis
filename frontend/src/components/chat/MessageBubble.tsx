import type { ReactNode } from 'react'

interface Props {
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  timestamp: string
  children?: ReactNode
  hideTools?: boolean
}

const styles: Record<string, string> = {
  user: 'justify-end',
  assistant: 'justify-start',
  system: 'justify-center',
  tool_call: 'justify-start',
  tool_result: 'justify-start',
}

const bubbles: Record<string, string> = {
  user: 'bg-blue-500 text-white rounded-2xl rounded-br-md',
  assistant: 'bg-gray-50 border border-gray-100 text-gray-800 rounded-2xl rounded-bl-md',
  tool_call: 'bg-violet-50 border border-violet-100 text-gray-700 rounded-xl',
  tool_result: 'bg-emerald-50 border border-emerald-100 text-gray-700 rounded-xl',
}

function renderContent(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-gray-900">$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="bg-gray-200 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">$1</code>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
}

export function MessageBubble({ role, content, timestamp, children, hideTools }: Props) {
  if (hideTools && (role === 'tool_call' || role === 'tool_result')) {
    return null
  }
  if (role === 'system') {
    return (
      <div className="flex justify-center py-1">
        <span className="text-xs text-gray-400">{content}</span>
      </div>
    )
  }

  const timeStr = new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const bubble = bubbles[role] || bubbles.assistant

  return (
    <div className={`flex ${styles[role] || 'justify-start'} mb-3`}>
      <div className={`max-w-[85%] px-4 py-2.5 ${bubble}`}>
        {role === 'assistant' ? (
          <div className="text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: renderContent(content) }} />
        ) : (
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{content}</p>
        )}
        {children}
        <p className={`text-[10px] mt-1.5 ${role === 'user' ? 'text-blue-200' : 'text-gray-400'}`}>
          {timeStr}
        </p>
      </div>
    </div>
  )
}
