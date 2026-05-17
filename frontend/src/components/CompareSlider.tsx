import { useState, useRef, useCallback } from 'react'
import { GripVertical } from 'lucide-react'

interface CompareSliderProps {
  srcBefore: string
  srcAfter: string
  labelBefore?: string
  labelAfter?: string
}

export default function CompareSlider({
  srcBefore,
  srcAfter,
  labelBefore = '上次结果',
  labelAfter = '本次结果',
}: CompareSliderProps) {
  const [split, setSplit] = useState(50)
  const [dragging, setDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleMove = useCallback((e: React.MouseEvent | MouseEvent) => {
    if (!dragging || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    setSplit(Math.max(5, Math.min(95, (x / rect.width) * 100)))
  }, [dragging])

  const handleMouseDown = () => setDragging(true)
  const handleMouseUp = () => setDragging(false)

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden select-none rounded-xl"
      onMouseMove={handleMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {/* 底层：before（右半） */}
      <img
        src={srcBefore}
        alt={labelBefore}
        className="absolute inset-0 w-full h-full object-contain bg-gray-100"
        draggable={false}
      />

      {/* 顶层：after（左半，clip 控制） */}
      <img
        src={srcAfter}
        alt={labelAfter}
        className="absolute inset-0 w-full h-full object-contain bg-gray-100"
        style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
        draggable={false}
      />

      {/* 分割线 */}
      <div
        className="absolute top-0 bottom-0 w-1 bg-white shadow-lg cursor-col-resize z-10"
        style={{ left: `${split}%`, transform: 'translateX(-50%)' }}
        onMouseDown={handleMouseDown}
      >
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 bg-white rounded-full shadow-md flex items-center justify-center">
          <GripVertical className="h-4 w-4 text-gray-500" />
        </div>
      </div>

      {/* 标签 */}
      <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">
        {labelAfter}
      </div>
      <div className="absolute top-3 right-3 bg-black/60 text-white text-xs px-2 py-1 rounded z-10">
        {labelBefore}
      </div>
    </div>
  )
}
