/**
 * SSE (Server-Sent Events) 客户端 — 支持指数退避重连
 */
import type { SSEEvent, SSEEventType } from '../types'

export interface SSEConnectOptions {
  convId: number
  content: string
  onEvent: (event: SSEEvent) => void
  onError?: (error: Error) => void
  onDone?: () => void
  onRetry?: (attempt: number, delay: number) => void
  signal?: AbortSignal
  maxRetries?: number
}

/**
 * 连接到 SSE 端点，实时接收 Agent 执行事件。
 * 支持指数退避自动重连（默认最多 3 次）。
 * 返回 abort 函数用于取消连接。
 */
export function connectSSE(options: SSEConnectOptions): () => void {
  const { convId, content, onEvent, onError, onDone, onRetry, signal, maxRetries = 3 } = options

  let retryCount = 0
  let stopped = false
  const controller = new AbortController()

  if (signal) {
    signal.addEventListener('abort', () => { stopped = true; controller.abort() })
  }

  function cleanup() {
    stopped = true
    controller.abort()
  }

  function tryConnect() {
    if (stopped) return

    const token = localStorage.getItem('token')
    const url = `/api/conversations/${convId}/messages/stream`

    fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })
      .then(async (response) => {
        // 404 不重试（会话不存在）
        if (response.status === 404) {
          onError?.(new Error(`会话不存在或已被删除 (404)`))
          return
        }
        // 其他非 200 状态码：指数退避重试
        if (!response.ok) {
          throw new Error(`SSE 连接失败: ${response.status}`)
        }

        // 连接成功，重置重试计数
        retryCount = 0

        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error('无法读取响应流')
        }

        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          if (stopped) { reader.cancel(); return }
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          let currentEventType = ''
          let currentData = ''

          for (const line of lines) {
            if (line.startsWith(': heartbeat')) {
              // 心跳行，忽略
              continue
            }
            if (line.startsWith('event: ')) {
              currentEventType = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              currentData = line.slice(6).trim()
            } else if (line === '') {
              if (currentEventType && currentData) {
                try {
                  const data = JSON.parse(currentData)
                  onEvent({ type: currentEventType as SSEEventType, data })
                } catch { /* JSON 解析失败，忽略 */ }

                if (currentEventType === 'done') {
                  onDone?.()
                  return
                }
              }
              currentEventType = ''
              currentData = ''
            }
          }
        }

        // 流自然结束
        onDone?.()
      })
      .catch((err) => {
        if ((err as Error).name === 'AbortError' || stopped) return

        // 指数退避重试
        if (retryCount < maxRetries) {
          retryCount++
          const delay = Math.min(1000 * Math.pow(2, retryCount), 10000) // 2s, 4s, 8s, max 10s
          onRetry?.(retryCount, delay)
          setTimeout(tryConnect, delay)
        } else {
          onError?.(err as Error)
        }
      })
  }

  tryConnect()

  return cleanup
}
