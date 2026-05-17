/**
 * OpenGIS 统一状态管理（替代 authStore + taskStore + workspaceStore）
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Task, User } from '../types'
import { authService } from '../services/auth'
import { tasksService } from '../services/tasks'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  taskId?: number
}

export interface OutputFile {
  name: string
  path: string
  relative_path?: string
  size: number
  modified: string
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
  isLoadingTasks: boolean

  // Actions - 用户
  login: (username: string, password: string) => Promise<boolean>
  register: (username: string, email: string, password: string) => Promise<boolean>
  logout: () => void
  fetchUser: () => Promise<void>

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
  createTask: (input: string) => Promise<Task>
  cancelTask: (taskId: number) => Promise<void>
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
      isLoadingTasks: false,

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
      createTask: async (input) => {
        const task = await tasksService.createTask({ input_text: input })
        set(s => ({ recentTasks: [task, ...s.recentTasks.slice(0, 19)] }))
        return task
      },
      cancelTask: async (taskId) => {
        await tasksService.cancelTask(taskId)
        set(s => ({ recentTasks: s.recentTasks.map(t => t.id === taskId ? { ...t, status: 'cancelled' as const } : t) }))
      },
    }),
    {
      name: 'opengis-v2',
      partialize: (state) => ({
        messages: state.messages,
        sidebarCollapsed: state.sidebarCollapsed,
        token: state.token,
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
