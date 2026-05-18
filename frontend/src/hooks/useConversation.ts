import { useState, useCallback, useRef } from 'react'
import type { ToolCall, ExecutionPhase, SSEEventType } from '../types/conversation'

interface UseConversationReturn {
  phase: ExecutionPhase
  toolCalls: ToolCall[]
  answer: string
  send: (convId: number, content: string) => Promise<void>
  abort: () => void
}

export function useConversation(): UseConversationReturn {
  const [phase, setPhase] = useState<ExecutionPhase>('idle')
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [answer, setAnswer] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const phaseRef = useRef<ExecutionPhase>('idle')

  const updatePhase = useCallback((p: ExecutionPhase) => {
    phaseRef.current = p
    setPhase(p)
  }, [])

  const send = useCallback(async (convId: number, content: string) => {
    updatePhase('thinking')
    setAnswer('')
    setToolCalls([])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/conversations/${convId}/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const errBody = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}${errBody ? ': ' + errBody.slice(0, 100) : ''}`)
      }

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let eventType = ''
        let eventData = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            // 如果之前有完整事件，先处理
            if (eventType && eventData) {
              try {
                const data = JSON.parse(eventData)
                handleEvent(eventType as SSEEventType, data)
              } catch { /* skip */ }
            }
            eventType = line.slice(7).trim()
            eventData = ''
          } else if (line.startsWith('data: ')) {
            eventData += line.slice(6)
          } else if (line === '' && eventType && eventData) {
            try {
              const data = JSON.parse(eventData)
              handleEvent(eventType as SSEEventType, data)
            } catch { /* skip malformed events */ }
            eventType = ''
            eventData = ''
          }
        }

        // 处理最后一个可能不完整的event
        if (eventType && eventData) {
          // Don't clear - it might be incomplete, wait for more data
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') {
        updatePhase('done')
        setAnswer(`连接错误: ${(err as Error).message}`)
      }
    }
  }, [updatePhase])

  function handleEvent(type: SSEEventType, data: Record<string, unknown>) {
    switch (type) {
      case 'step_start':
        updatePhase('executing')
        break
      case 'tool_start':
        setToolCalls((prev) => [
          ...prev,
          {
            tool: data.tool as string,
            args: data.args as Record<string, unknown>,
            status: 'running' as const,
          },
        ])
        break
      case 'tool_result': {
        const toolName = data.tool as string
        const result = data.result as Record<string, unknown>
        setToolCalls((prev) =>
          prev.map((tc) =>
            tc.tool === toolName && tc.status === 'running'
              ? { ...tc, result, status: result?.success === false ? ('error' as const) : ('success' as const) }
              : tc
          )
        )
        break
      }
      case 'ask_user': {
        const question = data.question as string
        setAnswer(question)
        updatePhase('waiting_for_user')
        break
      }
      case 'final_answer':
        setAnswer(data.content as string)
        updatePhase('done')
        break
      case 'error':
        setAnswer(`错误: ${data.message}`)
        updatePhase('done')
        break
      case 'done':
        if (phaseRef.current !== 'done') updatePhase('done')
        break
    }
  }

  const abort = useCallback(() => {
    abortRef.current?.abort()
    updatePhase('idle')
  }, [updatePhase])

  return { phase, toolCalls, answer, send, abort }
}
