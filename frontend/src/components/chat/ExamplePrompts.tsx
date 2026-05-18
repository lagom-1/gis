import { useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'

interface Props { onSelect: (text: string) => void }

const EXAMPLES = [
  '下载成都市双流区2024年8月LST并制图',
  '生成北京市2020-2024年LST时间序列动画',
  '把图例移到左侧，配色改成 viridis',
  '对当前结果做自然断点分类',
  '查看刚才下载的影像元数据',
]

export function ExamplePrompts({ onSelect }: Props) {
  const [show, setShow] = useState(true)

  return (
    <div className="mt-3">
      <button
        onClick={() => setShow(!show)}
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors mb-2"
      >
        <Sparkles className="h-3 w-3" />
        试试这些示例
        {show ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {show && (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex, i) => (
            <button
              key={i}
              onClick={() => onSelect(ex)}
              className="text-xs px-2.5 py-1.5 bg-gray-50 hover:bg-gray-100 border border-gray-100 hover:border-gray-200 text-gray-500 hover:text-gray-700 rounded-full transition-colors truncate max-w-[260px]"
              title={ex}
            >
              {ex.length > 28 ? ex.slice(0, 28) + '...' : ex}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
