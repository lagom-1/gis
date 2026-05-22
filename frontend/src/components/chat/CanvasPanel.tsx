import { useState, useEffect, useMemo } from 'react'
import {
  ImageIcon, Film, FileText, Table2, Maximize2, X, Columns2, Download,
} from 'lucide-react'
import type { OutputFile } from '../../types/conversation'
import ViewerRouter from '../ViewerRouter'
import CompareSlider from '../CompareSlider'

interface Props {
  files: OutputFile[]
  onFileClick?: (file: OutputFile) => void
}

function getCategory(name: string) {
  if (/\.gif$/i.test(name)) return 'gif'
  if (/\.html$/i.test(name)) return 'html'
  if (/\.csv$/i.test(name)) return 'csv'
  if (/\.(tif|tiff)$/i.test(name)) return 'tif'
  return 'image'
}

function isBrowserViewable(name: string) {
  return /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(name)
}

function TabIcon({ cat }: { cat: string }) {
  const cls = "h-3.5 w-3.5 flex-shrink-0"
  switch (cat) {
    case 'gif': return <Film className={`${cls} text-emerald-500`} />
    case 'html': return <FileText className={`${cls} text-violet-500`} />
    case 'csv': return <Table2 className={`${cls} text-blue-500`} />
    case 'tif': return <FileText className={`${cls} text-amber-500`} />
    default: return <ImageIcon className={`${cls} text-blue-500`} />
  }
}

/**
 * 将后端返回的文件路径转换为前端可访问的 URL。
 * 路径示例: D:\opengis\workspace\outputs\旺苍县_2026年1月_LST_map.png
 * 转换为: /outputs/%E6%97%BA%E8%8B%8D%E5%8E%BF_2026%E5%B9%B41%E6%9C%88_LST_map.png
 */
function buildFileUrl(f: OutputFile): string {
  // 优先使用 relative_path，其次从绝对路径中提取 /outputs/ 之后的相对路径
  const raw = (f as any).relative_path || f.path || f.name
  const normalized = raw.replace(/\\/g, '/')
  // 处理已经是 /outputs/... 或以 outputs/ 开头的路径
  if (normalized.startsWith('/outputs/')) {
    return normalized.split('/').map(encodeURIComponent).join('/')
  }
  if (normalized.startsWith('outputs/')) {
    return '/' + normalized.split('/').map(encodeURIComponent).join('/')
  }
  // 从绝对路径中提取 /outputs/ 之后的部分 (使用 indexOf 找到第一个匹配)
  const idx = normalized.indexOf('/outputs/')
  if (idx >= 0) {
    const rel = normalized.slice(idx + 1) // "outputs/..."
    return '/' + rel.split('/').map(encodeURIComponent).join('/')
  }
  // 回退：假设文件在 outputs 根目录下
  return '/outputs/' + encodeURIComponent(f.name)
}

export function CanvasPanel({ files, onFileClick }: Props) {
  const [activeFile, setActiveFile] = useState<OutputFile | null>(null)
  const [compareMode, setCompareMode] = useState(false)
  const [lightbox, setLightbox] = useState(false)

  // 可对比的图片文件（排除 GIF/CSV/HTML）
  const comparableImages = useMemo(
    () => files.filter(f => getCategory(f.name) === 'image'),
    [files],
  )

  // 自动选择最新文件为激活，优先选浏览器可查看的图片（PNG/JPG），跳过 TIF
  useEffect(() => {
    if (files.length === 0) {
      setActiveFile(null)
      setCompareMode(false)
      return
    }
    setActiveFile(prev => {
      if (prev && files.some(f => f.name === prev.name)) return prev
      // 优先选浏览器可查看的图片
      const img = files.find(f => isBrowserViewable(f.name))
      return img || files[files.length - 1]
    })
  }, [files])

  const getUrl = buildFileUrl

  // 空状态
  if (files.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <div className="text-center text-gray-400 px-4">
          <ImageIcon className="h-12 w-12 mx-auto mb-3 opacity-20" />
          <p className="text-sm font-medium text-gray-500 mb-1">等待输出结果</p>
          <p className="text-xs">任务生成的文件将在这里预览</p>
        </div>
      </div>
    )
  }

  // 卷帘对比模式
  if (compareMode && comparableImages.length >= 2) {
    const latest = comparableImages[comparableImages.length - 1]
    const previous = comparableImages[comparableImages.length - 2]
    return (
      <div className="flex flex-col flex-1 min-h-0 bg-white">
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Columns2 className="h-3.5 w-3.5 text-blue-500" />
            <span className="text-xs font-medium text-gray-600">卷帘对比</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCompareMode(false)}
              className="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 rounded transition-colors"
            >
              退出对比
            </button>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          <CompareSlider
            srcBefore={getUrl(previous)}
            srcAfter={getUrl(latest)}
            labelBefore={previous.name}
            labelAfter={latest.name}
          />
        </div>
        <div className="px-3 py-1.5 border-t border-gray-100 flex items-center gap-3 text-xs text-gray-400">
          <span className="truncate">← {previous.name}</span>
          <span className="flex-shrink-0">|</span>
          <span className="truncate">{latest.name} →</span>
        </div>
      </div>
    )
  }

  // 常规单文件预览模式
  const cat = activeFile ? getCategory(activeFile.name) : 'image'
  const activeUrl = activeFile ? getUrl(activeFile) : ''

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-white">
      {/* 头部工具栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <TabIcon cat={cat} />
          <span className="text-xs font-semibold text-gray-600">预览</span>
          {files.length > 0 && (
            <span className="text-[10px] text-white bg-blue-500 px-1.5 py-0.5 rounded-full">{files.length}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {comparableImages.length >= 2 && !compareMode && (
            <button
              onClick={() => setCompareMode(true)}
              className="flex items-center gap-1 px-2 py-1 text-xs text-blue-600 bg-blue-50 hover:bg-blue-100 rounded transition-colors"
            >
              <Columns2 className="h-3 w-3" />
              对比
            </button>
          )}
          {activeFile && (
            <>
              <button
                onClick={() => setLightbox(true)}
                className="p-1.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
                title="全屏"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
              <a
                href={activeUrl}
                download={activeFile.name}
                className="p-1.5 text-gray-400 hover:text-blue-500 rounded transition-colors"
                title="下载"
              >
                <Download className="h-3.5 w-3.5" />
              </a>
            </>
          )}
        </div>
      </div>

      {/* 文件标签栏 */}
      <div className="flex items-center gap-0.5 px-2 py-1.5 border-b border-gray-50 overflow-x-auto flex-shrink-0">
        {files.map(f => {
          const c = getCategory(f.name)
          const isActive = activeFile?.name === f.name
          return (
            <button
              key={f.name}
              onClick={() => { setActiveFile(f); setCompareMode(false); onFileClick?.(f) }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs whitespace-nowrap transition-colors flex-shrink-0 ${
                isActive
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'text-gray-500 hover:bg-gray-50 border border-transparent'
              }`}
            >
              <TabIcon cat={c} />
              <span className="max-w-[100px] truncate">{f.name}</span>
            </button>
          )
        })}
      </div>

      {/* 画布查看区 — relative 定位容器，flex-1 min-h-0 拉伸填满剩余空间 */}
      <div className="flex-1 min-h-0 bg-gray-100 relative overflow-hidden">
        {activeFile && (
          <ViewerRouter
            file={activeFile}
            src={activeUrl}
          />
        )}
      </div>

      {/* 底部信息栏 */}
      {activeFile && (
        <div className="px-3 py-1.5 border-t border-gray-100 flex items-center gap-2 text-xs text-gray-400">
          <TabIcon cat={cat} />
          <span className="truncate">{activeFile.name}</span>
        </div>
      )}

      {/* 全屏灯箱 */}
      {lightbox && activeFile && (
        <div className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center" onClick={() => setLightbox(false)}>
          <button onClick={() => setLightbox(false)} className="absolute top-4 right-4 p-2 text-white/60 hover:text-white">
            <X className="h-6 w-6" />
          </button>
          <div className="w-full h-full p-8" onClick={e => e.stopPropagation()}>
            <ViewerRouter
              file={activeFile}
              src={activeUrl}
            />
          </div>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-white/50">{activeFile.name}</div>
        </div>
      )}
    </div>
  )
}
