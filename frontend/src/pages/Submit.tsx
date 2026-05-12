import { useNavigate } from 'react-router-dom'
import TaskInput from '../components/TaskInput'
import { useTaskStore } from '../stores/taskStore'
import toast from 'react-hot-toast'

export default function Submit() {
  const navigate = useNavigate()
  const { createTask, isLoading } = useTaskStore()

  const handleSubmit = async (text: string) => {
    try {
      const task = await createTask({ input_text: text })
      toast.success('任务已提交')
      navigate(`/tasks/${task.id}`)
    } catch {
      toast.error('任务提交失败')
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">新建 GIS 任务</h1>
      <div className="bg-white rounded-xl p-6 border">
        <TaskInput onSubmit={handleSubmit} isLoading={isLoading} />
      </div>
    </div>
  )
}
