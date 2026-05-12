import api from './api'
import type { Task, TaskCreateRequest } from '../types'

export const tasksService = {
  async createTask(data: TaskCreateRequest): Promise<Task> {
    const response = await api.post<Task>('/tasks', data)
    return response.data
  },

  async getTasks(params?: { status?: string; skip?: number; limit?: number }): Promise<Task[]> {
    const response = await api.get('/tasks', { params })
    return response.data.tasks
  },

  async getTask(taskId: number): Promise<Task> {
    const response = await api.get<Task>(`/tasks/${taskId}`)
    return response.data
  },

  async cancelTask(taskId: number): Promise<void> {
    await api.delete(`/tasks/${taskId}`)
  },
}
