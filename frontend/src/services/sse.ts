/**
 * SSE (Server-Sent Events) 客户端
 *
 * 用于接收 ConversationalAgent 的实时执行事件流。
 */

import type { SSEEvent, SSEEventType } from '../types'

export interface SSEConnectOptions {
  convId: number
  content: string
  onEvent: (event: SSEEvent) => void
  onError?: (error: Error) => void
  onDone?: () => void
  signal?: AbortSignal
}

/**
 * 连接到 SSE 端点，实时接收 Agent 执行事件。
 *
 * 返回一个 abort 函数用于取消连接。
 */
export function connectSSE(options: SSEConnectOptions): () => void {
  const { convId, content, onEvent, onError, onDone, signal } = options

  const controller = new AbortController()

  // 合并外部 signal 和内部 controller
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

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
      if (!response.ok) {
        throw new Error(`SSE 连接失败: ${response.status} ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('无法读取响应流')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 事件
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEventType = ''
        let currentData = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6).trim()
          } else if (line === '') {
            // 空行表示一个事件结束
            if (currentEventType && currentData) {
              try {
                const data = JSON.parse(currentData)
                onEvent({
                  type: currentEventType as SSEEventType,
                  data,
                })
              } catch {
                // 非 JSON 数据，忽略
              }

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

      onDone?.()
    })
    .catch((err) => {
      if ((err as Error).name === 'AbortError') return
      onError?.(err as Error)
    })

  // 返回 abort 函数
  return () => controller.abort()
}
