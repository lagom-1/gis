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

        // 流结束后处理最后一个事件
        if (eventType && eventData) {
          try {
            const data = JSON.parse(eventData)
            handleEvent(eventType as SSEEventType, data)
          } catch { /* skip malformed events */ }
        }
      }

      // 连接已关闭但未收到完成信号（后端崩溃或异常中断）
      if (phaseRef.current !== 'done' && phaseRef.current !== 'waiting_for_user') {
        updatePhase('done')
        setAnswer('连接已断开，任务可能未完成。请检查输出面板确认结果。')
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
            reason: data.reason as string | undefined,
          },
        ])
        break
      case 'tool_result': {
        const toolName = data.tool as string
        const result = data.result as Record<string, unknown>
        setToolCalls((prev) => {
          // 找到最后一个匹配的 tool_call，优先更新 status === 'running' 的，否则更新最后一个匹配的
          const runningIdx = prev.map((tc, i) => ({ tc, i })).filter(({ tc }) => tc.tool === toolName && tc.status === 'running').pop()?.i
          if (runningIdx !== undefined) {
            return prev.map((tc, i) =>
              i === runningIdx
                ? { ...tc, result, status: result?.success === false ? ('error' as const) : ('success' as const) }
                : tc
            )
          }
          // 回退：更新最后一个同名工具调用（处理 GEE 自动重试等场景）
          const lastIdx = prev.map((tc, i) => ({ tc, i })).filter(({ tc }) => tc.tool === toolName).pop()?.i
          if (lastIdx !== undefined) {
            return prev.map((tc, i) =>
              i === lastIdx
                ? { ...tc, result, status: result?.success === false ? ('error' as const) : ('success' as const) }
                : tc
            )
          }
          return prev
        })
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
