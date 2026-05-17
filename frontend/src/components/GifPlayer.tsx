import { useState, useRef, useEffect } from 'react'
import { Play, Pause, SkipBack, SkipForward, Gauge } from 'lucide-react'

interface GifPlayerProps {
  src: string
  filename: string
}

const SPEEDS = [0.5, 1, 2, 4] as const

export default function GifPlayer({ src, filename }: GifPlayerProps) {
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState<number>(1)
  const [frame, setFrame] = useState(0)
  const [totalFrames, setTotalFrames] = useState(1)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 解析 GIF 帧
  useEffect(() => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.src = src
    img.onload = () => {
      // 尝试从 GIF 中提取帧信息
      fetch(src)
        .then(r => r.arrayBuffer())
        .then(buf => {
          const arr = new Uint8Array(buf)
          // 简单解析 GIF 帧数：统计 Graphic Control Extension 块数
          let count = 0
          for (let i = 0; i < arr.length - 1; i++) {
            if (arr[i] === 0x21 && arr[i + 1] === 0xF9) count++
          }
          setTotalFrames(Math.max(count, 1))
        })
        .catch(() => setTotalFrames(4)) // fallback
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [src])

  // 播放控制
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)

    if (playing && totalFrames > 0) {
      const interval = Math.round(100 / speed) // 基准 100ms/帧
      timerRef.current = setInterval(() => {
        setFrame(f => (f + 1) % totalFrames)
      }, interval)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [playing, speed, totalFrames])

  const togglePlay = () => setPlaying(!playing)

  const stepForward = () => setFrame(f => (f + 1) % totalFrames)
  const stepBackward = () => setFrame(f => (f - 1 + totalFrames) % totalFrames)
  const cycleSpeed = () => {
    const idx = SPEEDS.indexOf(speed as typeof SPEEDS[number])
    setSpeed(SPEEDS[(idx + 1) % SPEEDS.length])
  }

  return (
    <div className="flex flex-col h-full">
      {/* GIF 画面 */}
      <div className="flex-1 flex items-center justify-center bg-gray-900 rounded-t-xl overflow-hidden min-h-0">
        <img
          src={src}
          alt={filename}
          className="max-w-full max-h-full object-contain"
          style={{ imageRendering: 'auto' }}
        />
      </div>

      {/* 控制栏 */}
      <div className="bg-gray-800 text-white px-4 py-2.5 flex items-center justify-between rounded-b-xl">
        <div className="flex items-center space-x-3">
          <button onClick={stepBackward} className="p-1 hover:bg-gray-700 rounded transition-colors" title="上一帧">
            <SkipBack className="h-4 w-4" />
          </button>
          <button onClick={togglePlay} className="p-1.5 bg-white/20 hover:bg-white/30 rounded-full transition-colors" title={playing ? '暂停' : '播放'}>
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 ml-0.5" />}
          </button>
          <button onClick={stepForward} className="p-1 hover:bg-gray-700 rounded transition-colors" title="下一帧">
            <SkipForward className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center space-x-3 text-xs">
          <span className="text-gray-400">第 {frame + 1}/{totalFrames} 帧</span>
          <button
            onClick={cycleSpeed}
            className="flex items-center space-x-1 px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded transition-colors"
            title="切换播放速率"
          >
            <Gauge className="h-3 w-3" />
            <span>{speed}x</span>
          </button>
        </div>
      </div>
    </div>
  )
}
