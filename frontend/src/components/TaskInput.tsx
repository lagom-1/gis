import { useState } from 'react'
import { Send } from 'lucide-react'

interface TaskInputProps {
  onSubmit: (text: string) => Promise<void>
  isLoading?: boolean
}

const examples = [
  '找到 Beijing 的 TIF 文件，做温度反演并制图',
  '下载上海地区 2023 年 Landsat 数据',
  '生成北京地区 2020-2024 年 LST 时间序列动画',
  '对 Landsat 影像进行无监督分类',
]

export default function TaskInput({ onSubmit, isLoading }: TaskInputProps) {
  const [text, setText] = useState('')
  const maxLength = 2000

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim() || isLoading) return
    if (text.length > maxLength) {
      return
    }
    await onSubmit(text.trim())
    setText('')
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            输入你的 GIS 任务需求
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, maxLength))}
            placeholder="例如：找到 Beijing 的 TIF 文件，做温度反演并制图"
            className="w-full h-32 px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent resize-none"
            disabled={isLoading}
            maxLength={maxLength}
          />
          <p className="text-xs text-gray-400 mt-1 text-right">{text.length}/{maxLength}</p>
        </div>
        <button
          type="submit"
          disabled={!text.trim() || isLoading}
          className="flex items-center justify-center space-x-2 w-full bg-primary-600 text-white py-3 px-4 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Send className="h-5 w-5" />
          <span>{isLoading ? '提交中...' : '提交任务'}</span>
        </button>
      </form>

      <div>
        <p className="text-sm text-gray-500 mb-2">示例任务：</p>
        <div className="flex flex-wrap gap-2">
          {examples.map((example, index) => (
            <button
              key={index}
              onClick={() => setText(example)}
              className="text-sm text-primary-600 hover:text-primary-700 bg-primary-50 hover:bg-primary-100 px-3 py-1 rounded-full transition-colors"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
