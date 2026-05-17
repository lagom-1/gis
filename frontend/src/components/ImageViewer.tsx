import { useState, useRef, useCallback } from 'react'
import { ZoomIn, ZoomOut, RotateCcw, Move } from 'lucide-react'

interface ImageViewerProps {
  src: string
  alt: string
  className?: string
}

export default function ImageViewer({ src, alt, className = '' }: ImageViewerProps) {
  const [scale, setScale] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const containerRef = useRef<HTMLDivElement>(null)

  const clampScale = (s: number) => Math.min(Math.max(s, 0.2), 10)

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? -0.2 : 0.2
    setScale(s => clampScale(s + delta))
  }, [])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (scale > 1) {
      setIsDragging(true)
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y })
    }
  }, [scale, position])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isDragging) {
      setPosition({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
    }
  }, [isDragging, dragStart])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  const resetView = useCallback(() => {
    setScale(1)
    setPosition({ x: 0, y: 0 })
  }, [])

  return (
    <div className={`relative group ${className}`} ref={containerRef}>
      {/* 缩放控件 */}
      <div className="absolute top-2 right-2 z-10 flex space-x-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => setScale(s => clampScale(s + 0.3))}
          className="p-1.5 bg-white/90 rounded-md shadow hover:bg-white transition-colors"
          title="放大"
        >
          <ZoomIn className="h-4 w-4 text-gray-600" />
        </button>
        <button
          onClick={() => setScale(s => clampScale(s - 0.3))}
          className="p-1.5 bg-white/90 rounded-md shadow hover:bg-white transition-colors"
          title="缩小"
        >
          <ZoomOut className="h-4 w-4 text-gray-600" />
        </button>
        <button
          onClick={resetView}
          className="p-1.5 bg-white/90 rounded-md shadow hover:bg-white transition-colors"
          title="重置"
        >
          <RotateCcw className="h-4 w-4 text-gray-600" />
        </button>
        <span className="p-1.5 text-xs text-gray-500 bg-white/90 rounded-md shadow font-mono">
          {Math.round(scale * 100)}%
        </span>
      </div>

      {/* 可拖拽缩放容器 */}
      <div
        className="overflow-hidden w-full h-full flex items-center justify-center"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: scale > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          style={{
            transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
            transition: isDragging ? 'none' : 'transform 0.15s ease-out',
          }}
          className="max-w-full max-h-full object-contain select-none"
        />
      </div>
      {scale > 1 && (
        <div className="absolute bottom-2 left-2 text-xs text-gray-400 bg-white/80 px-1.5 py-0.5 rounded">
          <Move className="h-3 w-3 inline mr-1" />
          拖拽平移
        </div>
      )}
    </div>
  )
}
