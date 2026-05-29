/**
 * OpenGIS 统一状态管理（替代 authStore + taskStore + workspaceStore）
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Conversation, OutputFile, SSEEvent, Task, User } from '../types'
import { authService } from '../services/auth'
import { conversationsService } from '../services/conversations'
import { connectSSE } from '../services/sse'
import { tasksService } from '../services/tasks'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  timestamp: string
  taskId?: number
  tool_name?: string
  tool_result?: Record<string, unknown>
}

interface AppState {
  // 用户
  user: User | null
  token: string | null

  // 对话
  messages: Message[]
  isProcessing: boolean
  activeTaskId: number | null
  executionStep: number
  executionTool: string

  // 输出
  currentOutput: OutputFile[]
  previousOutput: OutputFile[]
  previewFile: OutputFile | null
  showComparison: boolean
  fullscreenPreview: boolean

  // UI
  sidebarCollapsed: boolean
  activeTab: 'chat' | 'history'

  // 历史
  recentTasks: Task[]
  currentTask: Task | null
  isLoadingTasks: boolean

  // 会话
  activeConversationId: number | null
  conversations: Conversation[]
  isLoadingConversations: boolean
  streamingStatus: {
    phase: 'idle' | 'thinking' | 'executing' | 'waiting_for_user'
    step?: number
    maxSteps?: number
    tool?: string
    reason?: string
    question?: string
    options?: string[]
  }
  abortSSE: (() => void) | null

  // Actions - 用户
  login: (username: string, password: string) => Promise<boolean>
  register: (username: string, email: string, password: string) => Promise<boolean>
  logout: () => void
  fetchUser: () => Promise<void>
  setUser: (user: User | null) => void

  // Actions - 对话
  addMessage: (msg: Omit<Message, 'id' | 'timestamp'>) => void
  clearMessages: () => void
  setProcessing: (val: boolean, taskId?: number | null) => void
  setExecutionStep: (step: number, tool?: string) => void

  // Actions - 输出
  setCurrentOutput: (files: OutputFile[]) => void
  setPreviewFile: (file: OutputFile | null) => void
  setShowComparison: (show: boolean) => void
  setFullscreenPreview: (val: boolean) => void

  // Actions - UI
  setSidebarCollapsed: (val: boolean) => void
  setActiveTab: (tab: 'chat' | 'history') => void

  // Actions - 任务
  fetchRecentTasks: (silent?: boolean) => Promise<void>
  fetchTask: (taskId: number, silent?: boolean) => Promise<void>
  createTask: (input: string) => Promise<Task>
  cancelTask: (taskId: number) => Promise<void>

  // Actions - 会话
  setActiveConversation: (id: number | null) => void
  createConversation: (initialMessage?: string) => Promise<number>
  sendConversationMessage: (content: string) => Promise<void>
  fetchConversations: (silent?: boolean) => Promise<void>
  loadConversation: (id: number) => Promise<void>
  deleteConversation: (id: number) => Promise<void>
  setStreamingStatus: (status: Partial<AppState['streamingStatus']>) => void
  cancelSSE: () => void
}

function extractOutputFiles(result: Record<string, unknown> | undefined): OutputFile[] {
  if (!result || result.success === false) return []
  const seen = new Set<string>()
  const files: OutputFile[] = []
  const addFile = (name: string, path: string, size?: number, modified?: string) => {
    // 用文件名作为去重 key（同一文件不应因路径格式差异而重复）
    const key = name
    if (seen.has(key)) return
    seen.add(key)
    files.push({ name, path, size: size || 0, modified: modified || new Date().toISOString() })
  }
  for (const key of ['output_png', 'output_tif', 'output_gif', 'output_html', 'output_csv']) {
    const path = result[key]
    if (typeof path === 'string' && path) {
      const name = path.replace(/\\/g, '/').split('/').pop() || path
      addFile(name, path)
    }
  }
  const of = result.output_files
  if (Array.isArray(of)) {
    for (const f of of) {
      if (f && typeof f === 'object' && (f as Record<string, unknown>).name) {
        addFile(
          String((f as Record<string, unknown>).name),
          String((f as Record<string, unknown>).path || (f as Record<string, unknown>).name),
          Number((f as Record<string, unknown>).size || 0),
          String((f as Record<string, unknown>).modified || new Date().toISOString()),
        )
      }
    }
  }
  return files
}

const SYSTEM_MSG: Message = {
  id: 'sys',
  role: 'system',
  content: '你好！我是 GIS 遥感智能助手。输入你的需求，如：\n\n• "下载成都市双流区2024年8月LST并制图"\n• "改配色为 viridis"\n• "做自然断点分类"',
  timestamp: new Date().toISOString(),
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      user: null,
      token: localStorage.getItem('token'),
      messages: [SYSTEM_MSG],
      isProcessing: false,
      activeTaskId: null,
      executionStep: 0,
      executionTool: '',
      currentOutput: [],
      previousOutput: [],
      previewFile: null,
      showComparison: false,
      fullscreenPreview: false,
      sidebarCollapsed: false,
      activeTab: 'chat',
      recentTasks: [],
      currentTask: null,
      isLoadingTasks: false,
      activeConversationId: null,
      conversations: [],
      isLoadingConversations: false,
      streamingStatus: { phase: 'idle' },
      abortSSE: null,

      // ── 用户 ──
      login: async (username, password) => {
        try {
          const res = await authService.login({ username, password })
          localStorage.setItem('token', res.access_token)
          set({ token: res.access_token })
          const user = await authService.getMe()
          set({ user })
          return true
        } catch { return false }
      },
      register: async (username, email, password) => {
        try {
          await authService.register({ username, email, password })
          return true
        } catch { return false }
      },
      logout: () => { localStorage.removeItem('token'); set({ user: null, token: null }) },
      fetchUser: async () => {
        const token = get().token
        if (!token) return
        try { const user = await authService.getMe(); set({ user }) } catch { /* token expired */ }
      },
      setUser: (user) => set({ user }),

      // ── 对话 ──
      addMessage: (msg) => {
        const m: Message = { ...msg, id: Date.now().toString(), timestamp: new Date().toISOString() }
        set(s => ({ messages: [...s.messages, m] }))
      },
      clearMessages: () => set({ messages: [SYSTEM_MSG] }),
      setProcessing: (val, taskId) => set({ isProcessing: val, activeTaskId: taskId ?? null }),
      setExecutionStep: (step, tool) => set({ executionStep: step, executionTool: tool || '' }),

      // ── 输出 ──
      setCurrentOutput: (files) => set(s => ({
        currentOutput: files,
        previousOutput: s.currentOutput.length > 0 ? s.currentOutput : s.previousOutput,
      })),
      setPreviewFile: (file) => set({ previewFile: file }),
      setShowComparison: (show) => set({ showComparison: show }),
      setFullscreenPreview: (val) => set({ fullscreenPreview: val }),

      // ── UI ──
      setSidebarCollapsed: (val) => set({ sidebarCollapsed: val }),
      setActiveTab: (tab) => set({ activeTab: tab }),

      // ── 任务 ──
      fetchRecentTasks: async (silent) => {
        if (!silent) set({ isLoadingTasks: true })
        try {
          const tasks = await tasksService.getTasks()
          set({ recentTasks: tasks, isLoadingTasks: false })
        } catch { set({ isLoadingTasks: false }) }
      },
      fetchTask: async (taskId, silent) => {
        if (!silent) set({ isLoadingTasks: true })
        try {
          const task = await tasksService.getTask(taskId)
          set({ currentTask: task, isLoadingTasks: false })
        } catch { set({ isLoadingTasks: false }) }
      },
      createTask: async (input) => {
        const task = await tasksService.createTask({ input_text: input })
        set(s => ({ recentTasks: [task, ...s.recentTasks.slice(0, 19)] }))
        return task
      },
      cancelTask: async (taskId) => {
        await tasksService.cancelTask(taskId)
        set(s => ({ recentTasks: s.recentTasks.map(t => t.id === taskId ? { ...t, status: 'cancelled' as const } : t) }))
      },

      // ── 会话 ──
      setActiveConversation: (id) => set({ activeConversationId: id }),

      createConversation: async (initialMessage) => {
        const conv = await conversationsService.createConversation({
          initial_message: initialMessage,
        })
        set(s => ({
          conversations: [conv, ...s.conversations],
          activeConversationId: conv.id,
        }))
        if (initialMessage) {
          const content = initialMessage
          // 添加用户消息到本地 messages
          get().addMessage({ role: 'user', content })
        }
        return conv.id
      },

      sendConversationMessage: async (content) => {
        const state = get()
        let convId = state.activeConversationId

        // 如果没有活跃会话，自动创建一个
        if (!convId) {
          try {
            convId = await get().createConversation(content.slice(0, 50))
          } catch {
            get().addMessage({ role: 'system', content: '创建会话失败，请检查后端服务是否运行。' })
            return
          }
        }

        if (!convId || convId <= 0) {
          get().addMessage({ role: 'system', content: '会话 ID 无效，请刷新页面后重试。' })
          return
        }

        // 添加用户消息
        get().addMessage({ role: 'user', content })

        // 设置流式状态
        set({
          isProcessing: true,
          activeConversationId: convId,
          streamingStatus: { phase: 'thinking' },
        })

        // 打开 SSE 连接
        const abort = connectSSE({
          convId,
          content,
          onEvent: (event: SSEEvent) => {
            const s = get()
            switch (event.type) {
              case 'step_start':
                set({
                  streamingStatus: {
                    ...s.streamingStatus,
                    phase: 'executing',
                    step: event.data.step as number,
                    maxSteps: event.data.max as number,
                  },
                  executionStep: event.data.step as number,
                })
                break
              case 'tool_start':
                set({
                  streamingStatus: {
                    ...s.streamingStatus,
                    phase: 'executing',
                    tool: event.data.tool as string,
                    reason: event.data.reason as string,
                  },
                  executionTool: event.data.tool as string,
                })
                break
              case 'tool_result': {
                const result = event.data.result as Record<string, unknown>
                const ok = result?.success !== false
                const toolName = event.data.tool as string
                const uiAction = event.data.ui_action as string || 'NONE'

                // 提取输出文件（按 name 去重，避免路径格式差异导致重复）
                const files = extractOutputFiles(result)
                if (files.length > 0) {
                  const newNames = new Set(files.map(f => f.name))
                  set(s => ({
                    currentOutput: [
                      ...s.currentOutput.filter(existing => !newNames.has(existing.name)),
                      ...files,
                    ],
                  }))
                }

                // 根据 ui_action 自动设置预览
                if (files.length > 0 && uiAction !== 'NONE') {
                  set({ previewFile: files[0] })
                }

                get().addMessage({
                  role: 'tool_result',
                  content: ok
                    ? `✓ ${toolName} 执行成功: ${result?.message || ''}`
                    : `✗ ${toolName} 执行失败: ${result?.message || ''}`,
                  tool_name: toolName,
                  tool_result: result,
                  taskId: s.activeTaskId ?? undefined,
                })
                break
              }
              case 'ask_user':
                set({
                  streamingStatus: {
                    phase: 'waiting_for_user',
                    question: event.data.question as string,
                    options: event.data.options as string[],
                  },
                })
                break
              case 'final_answer':
                get().addMessage({
                  role: 'assistant',
                  content: event.data.content as string,
                })
                set({
                  isProcessing: false,
                  streamingStatus: { phase: 'idle' },
                  abortSSE: null,
                })
                break
              case 'error':
                get().addMessage({
                  role: 'system',
                  content: `错误: ${event.data.message}`,
                })
                set({
                  isProcessing: false,
                  streamingStatus: { phase: 'idle' },
                  abortSSE: null,
                })
                break
            }
          },
          onRetry: (attempt, delay) => {
            set({
              streamingStatus: {
                phase: 'executing',
                reason: `连接中断，${delay / 1000}秒后重试 (${attempt}/3)...`,
              },
            })
          },
          onError: (error) => {
            get().addMessage({
              role: 'system',
              content: `连接错误: ${error.message}`,
            })
            set({
              isProcessing: false,
              streamingStatus: { phase: 'idle' },
              abortSSE: null,
            })
          },
          onDone: () => {
            get().fetchConversations(true)
          },
        })

        set({ abortSSE: abort })
      },

      fetchConversations: async (silent) => {
        if (!silent) set({ isLoadingConversations: true })
        try {
          const result = await conversationsService.getConversations()
          const s = get()
          // 如果 localStorage 中残留的 convId 不在服务端列表中，清除它
          if (s.activeConversationId && !result.conversations.some(c => c.id === s.activeConversationId)) {
            set({ activeConversationId: null })
          }
          set({ conversations: result.conversations, isLoadingConversations: false })
        } catch {
          set({ isLoadingConversations: false })
        }
      },

      loadConversation: async (id) => {
        set({ activeConversationId: id, currentOutput: [], previousOutput: [], previewFile: null })
        try {
          const result = await conversationsService.getMessages(id, { limit: 100 })
          const msgs = result.messages.map(m => ({
            id: m.id.toString(),
            role: (['user', 'assistant', 'tool_call', 'tool_result'].includes(m.role)
              ? m.role : 'system') as Message['role'],
            content: m.content,
            timestamp: m.created_at,
            tool_name: m.tool_name,
            tool_result: m.tool_result,
          }))
          if (msgs.length > 0) {
            set({
              messages: [SYSTEM_MSG, ...msgs.filter(m =>
                m.role !== 'system' || m.content?.startsWith('错误')
              )],
            })
          }
        } catch {
          // ignore
        }
      },

      deleteConversation: async (id) => {
        await conversationsService.deleteConversation(id)
        set(s => ({
          conversations: s.conversations.filter(c => c.id !== id),
          activeConversationId: s.activeConversationId === id ? null : s.activeConversationId,
        }))
      },

      setStreamingStatus: (status) => set(s => ({
        streamingStatus: { ...s.streamingStatus, ...status },
      })),

      cancelSSE: () => {
        const { abortSSE } = get()
        if (abortSSE) {
          abortSSE()
          set({
            abortSSE: null,
            isProcessing: false,
            streamingStatus: { phase: 'idle' },
          })
        }
      },
    }),
    {
      name: 'opengis-v2',
      partialize: (state) => ({
        messages: state.messages,
        sidebarCollapsed: state.sidebarCollapsed,
        token: state.token,
        activeConversationId: state.activeConversationId,
      }),
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<AppState>),
        currentOutput: [], previousOutput: [], previewFile: null,
        showComparison: false, fullscreenPreview: false,
        isProcessing: false, activeTaskId: null,
        messages: (persisted as Partial<AppState>).messages?.length
          ? [{ ...SYSTEM_MSG, timestamp: new Date().toISOString() },
             ...(persisted as Partial<AppState>).messages!.filter(m => m.role !== 'system')]
          : current.messages,
      }),
    },
  ),
)
