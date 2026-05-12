import { useEffect } from 'react'
import { useTaskStore } from '../stores/taskStore'

export function useTasks(status?: string) {
  const { tasks, currentTask, isLoading, error, fetchTasks, fetchTask, createTask, cancelTask } =
    useTaskStore()

  useEffect(() => {
    fetchTasks({ status })
  }, [fetchTasks, status])

  return {
    tasks,
    currentTask,
    isLoading,
    error,
    fetchTasks,
    fetchTask,
    createTask,
    cancelTask,
  }
}
