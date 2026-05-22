import { useState, useRef, useCallback } from 'react'
import { ZoomIn, ZoomOut, RotateCcw, Move, ImageOff } from 'lucide-react'

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
  const [imgError, setImgError] = useState(false)
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

  // 图片加载失败时显示错误占位
  if (imgError) {
    return (
      <div className={`flex items-center justify-center bg-gray-100 rounded ${className}`}>
        <div className="text-center text-gray-400 px-4">
          <ImageOff className="h-10 w-10 mx-auto mb-2 opacity-40" />
          <p className="text-sm font-medium text-gray-500">图片加载失败</p>
          <p className="text-xs mt-1 text-gray-400 max-w-[200px] truncate" title={alt}>{alt}</p>
          <button
            onClick={() => setImgError(false)}
            className="mt-3 px-3 py-1.5 text-xs text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
          >
            重试
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={`group ${className || 'relative w-full h-full'}`} ref={containerRef}>
      {/* 缩放控件 (绝对定位，浮在图片上方) */}
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

      {/* 可拖拽缩放容器 — 使用 absolute inset-0 确保填满父元素，不受 h-full 高度链影响 */}
      <div
        className="absolute inset-0 overflow-hidden flex items-center justify-center"
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
          onError={() => setImgError(true)}
          onLoad={() => setImgError(false)}
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
