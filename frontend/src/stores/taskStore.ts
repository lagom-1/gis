import { create } from 'zustand'
import type { Task, TaskCreateRequest } from '../types'
import { tasksService } from '../services/tasks'

interface TaskState {
  tasks: Task[]
  currentTask: Task | null
  isLoading: boolean
  error: string | null
  fetchTasks: (params?: { status?: string; silent?: boolean }) => Promise<void>
  fetchTask: (taskId: number, silent?: boolean) => Promise<void>
  createTask: (data: TaskCreateRequest) => Promise<Task>
  cancelTask: (taskId: number) => Promise<void>
}

export const useTaskStore = create<TaskState>((set) => ({
  tasks: [],
  currentTask: null,
  isLoading: false,
  error: null,

  fetchTasks: async (params, silent = false) => {
    if (!silent) set({ isLoading: true, error: null })
    try {
      const tasks = await tasksService.getTasks(params)
      set({ tasks, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '获取任务列表失败', isLoading: false })
    }
  },

  fetchTask: async (taskId, silent = false) => {
    if (!silent) {
      set({ isLoading: true, error: null })
    }
    try {
      const task = await tasksService.getTask(taskId)
      set({ currentTask: task, isLoading: false })
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '获取任务详情失败', isLoading: false })
    }
  },

  createTask: async (data) => {
    set({ isLoading: true, error: null })
    try {
      const task = await tasksService.createTask(data)
      set((state) => ({ currentTask: task, tasks: [task, ...state.tasks], isLoading: false }))
      return task
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '创建任务失败', isLoading: false })
      throw error
    }
  },

  cancelTask: async (taskId) => {
    try {
      await tasksService.cancelTask(taskId)
      set((state) => ({
        tasks: state.tasks.map((t) =>
          t.id === taskId ? { ...t, status: 'cancelled' as const } : t
        ),
      }))
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '取消任务失败' })
    }
  },
}))
