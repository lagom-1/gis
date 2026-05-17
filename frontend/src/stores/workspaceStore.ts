import { create } from 'zustand'
import { persist } from 'zustand/middleware'

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

interface WorkspaceState {
  messages: Message[]
  currentOutput: OutputFile[]
  previousOutput: OutputFile[]
  previewFile: OutputFile | null
  showComparison: boolean
  sidebarCollapsed: boolean

  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => void
  loadProjectMessages: (msgs: Array<{ role: string; content: string; timestamp: string; task_id?: number }>) => void
  clearMessages: () => void
  setCurrentOutput: (files: OutputFile[]) => void
  setPreviousOutput: (files: OutputFile[]) => void
  setPreviewFile: (file: OutputFile | null) => void
  setShowComparison: (show: boolean) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  reset: () => void
}

const SYSTEM_MESSAGE: Message = {
  id: 'system-1',
  role: 'system',
  content: '你好！我是 GIS 智能助手。你可以告诉我你的需求，比如：\n\n• "下载成都市双流区2022-2025年8月的Landsat数据，做温度反演"\n• "把刚才的结果改成热力图风格"\n• "生成时间序列GIF动画"\n• "调整图例范围为20-45度"',
  timestamp: new Date().toISOString(),
}

const initialState = {
  messages: [SYSTEM_MESSAGE] as Message[],
  currentOutput: [] as OutputFile[],
  previousOutput: [] as OutputFile[],
  previewFile: null as OutputFile | null,
  showComparison: false,
  sidebarCollapsed: false,
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      ...initialState,

      addMessage: (message) => {
        const newMessage: Message = {
          ...message,
          id: Date.now().toString(),
          timestamp: new Date().toISOString(),
        }
        set((state) => ({
          messages: [...state.messages, newMessage],
        }))
      },

      loadProjectMessages: (msgs) => {
        const loaded: Message[] = msgs.map((m, i) => ({
          id: `loaded-${i}`,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: m.timestamp,
          taskId: m.task_id,
        }))
        set({ messages: [SYSTEM_MESSAGE, ...loaded] })
      },

      clearMessages: () => {
        set({ messages: [SYSTEM_MESSAGE] })
      },

      setCurrentOutput: (files) => {
        set((state) => {
          const newPrevious = state.currentOutput.length > 0 ? state.currentOutput : state.previousOutput
          return {
            currentOutput: files,
            previousOutput: newPrevious,
            showComparison: newPrevious.length > 0 && files.length > 0,
          }
        })
      },

      setPreviousOutput: (files) => set({ previousOutput: files }),
      setPreviewFile: (file) => set({ previewFile: file }),
      setShowComparison: (show) => set({ showComparison: show }),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      reset: () => {
        set(initialState)
      },
    }),
    {
      name: 'opengis-workspace',
      partialize: (state) => ({
        messages: state.messages,
        sidebarCollapsed: state.sidebarCollapsed,
      }),
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<WorkspaceState>),
        currentOutput: [],
        previousOutput: [],
        previewFile: null,
        showComparison: false,
        // 确保系统消息始终在开头，且时间戳刷新
        messages: (persisted as Partial<WorkspaceState>).messages?.length
          ? [
              { ...SYSTEM_MESSAGE, timestamp: new Date().toISOString() },
              ...(persisted as Partial<WorkspaceState>).messages!.filter(m => m.role !== 'system'),
            ]
          : current.messages,
      }),
    },
  ),
)
