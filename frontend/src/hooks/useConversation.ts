import { useState, useCallback, useRef } from 'react'
import type { ToolCall, ExecutionPhase, SSEEventType } from '../types/conversation'
import { connectSSE } from '../services/sse'
import type { SSEConnectOptions } from '../services/sse'

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

  const handleEvent = useCallback((type: SSEEventType, data: Record<string, unknown>) => {
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
          const runningIdx = prev.map((tc, i) => ({ tc, i })).filter(({ tc }) => tc.tool === toolName && tc.status === 'running').pop()?.i
          if (runningIdx !== undefined) {
            return prev.map((tc, i) =>
              i === runningIdx
                ? { ...tc, result, status: result?.success === false ? ('error' as const) : ('success' as const) }
                : tc
            )
          }
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
        setAnswer(data.question as string)
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
  }, [updatePhase])

  const send = useCallback(async (convId: number, content: string) => {
    if (!convId || convId <= 0) {
      setAnswer('会话 ID 无效，请刷新页面后重试。')
      return
    }
    updatePhase('thinking')
    setAnswer('')
    setToolCalls([])

    const controller = new AbortController()
    abortRef.current = controller

    const onEvent: SSEConnectOptions['onEvent'] = (event) => {
      if (event.type === 'heartbeat') return
      handleEvent(event.type as SSEEventType, event.data)
    }

    const onDone = () => {
      if (phaseRef.current !== 'done' && phaseRef.current !== 'waiting_for_user') {
        updatePhase('done')
        setAnswer('连接已断开，任务可能未完成。')
      }
    }

    const onRetry = (attempt: number, delay: number) => {
      setAnswer(`连接中断，${delay / 1000}秒后重试 (${attempt}/3)...`)
    }

    const onError = (error: Error) => {
      if (error.name === 'AbortError') return
      updatePhase('done')
      setAnswer(`连接错误: ${error.message}`)
    }

    connectSSE({
      convId,
      content,
      onEvent,
      onError,
      onDone,
      onRetry,
      signal: controller.signal,
    })
  }, [updatePhase, handleEvent])

  const abort = useCallback(() => {
    abortRef.current?.abort()
    updatePhase('idle')
  }, [updatePhase])

  return { phase, toolCalls, answer, send, abort }
}
