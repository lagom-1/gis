import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  ImageIcon, Film, FileText, Table2, Maximize2, X, Columns2, Download,
  ArrowLeftRight,
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

// ── 文件路径 → URL ──
function buildFileUrl(f: OutputFile): string {
  const raw = (f as any).relative_path || f.path || f.name
  const normalized = raw.replace(/\\/g, '/')
  if (normalized.startsWith('/outputs/')) {
    return normalized.split('/').map(encodeURIComponent).join('/')
  }
  if (normalized.startsWith('outputs/')) {
    return '/' + normalized.split('/').map(encodeURIComponent).join('/')
  }
  const idx = normalized.indexOf('/outputs/')
  if (idx >= 0) {
    const rel = normalized.slice(idx + 1)
    return '/' + rel.split('/').map(encodeURIComponent).join('/')
  }
  return '/outputs/' + encodeURIComponent(f.name)
}

export function CanvasPanel({ files, onFileClick }: Props) {
  const [activeFile, setActiveFile] = useState<OutputFile | null>(null)
  const [compareMode, setCompareMode] = useState(false)
  const [lightbox, setLightbox] = useState(false)

  // 可对比的图片文件
  const comparableImages = useMemo(
    () => files.filter(f => getCategory(f.name) === 'image'),
    [files],
  )

  // 卷帘对比的左右选中文件（用 name 做 key）
  const [leftFile, setLeftFileRaw] = useState<OutputFile | null>(null)
  const [rightFile, setRightFileRaw] = useState<OutputFile | null>(null)

  // 包装 setter：同时根据 name 在 files 中查找最新引用
  const setLeftFile = useCallback((f: OutputFile | null) => {
    if (!f) { setLeftFileRaw(null); return }
    const latest = files.find(x => x.name === f.name)
    setLeftFileRaw(latest || f)
  }, [files])
  const setRightFile = useCallback((f: OutputFile | null) => {
    if (!f) { setRightFileRaw(null); return }
    const latest = files.find(x => x.name === f.name)
    setRightFileRaw(latest || f)
  }, [files])

  // 进入对比模式时自动初始化左右文件为最后两个
  useEffect(() => {
    if (compareMode && comparableImages.length >= 2) {
      const len = comparableImages.length
      // 只在首次进入（leftFile/rightFile 为空）时自动设置
      setLeftFileRaw(prev => prev || comparableImages[len - 2])
      setRightFileRaw(prev => prev || comparableImages[len - 1])
    }
  }, [compareMode, comparableImages])

  // 退出对比时重置
  useEffect(() => {
    if (!compareMode) {
      setLeftFileRaw(null)
      setRightFileRaw(null)
    }
  }, [compareMode])

  // 自动选择最新文件为激活
  useEffect(() => {
    if (files.length === 0) {
      setActiveFile(null)
      setCompareMode(false)
      return
    }
    setActiveFile(prev => {
      if (prev && files.some(f => f.name === prev.name)) return prev
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

  // ── 卷帘对比模式 ──
  if (compareMode && comparableImages.length >= 2) {
    const left = leftFile || comparableImages[comparableImages.length - 2]
    const right = rightFile || comparableImages[comparableImages.length - 1]
    const leftUrl = getUrl(left)
    const rightUrl = getUrl(right)
    const leftName = left.name
    const rightName = right.name

    return (
      <div className="flex flex-col flex-1 min-h-0 bg-white">
        {/* 工具栏：双下拉 + 退出 */}
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-gray-100 gap-1.5 flex-wrap">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <Columns2 className="h-3.5 w-3.5 text-blue-500 flex-shrink-0" />
            <span className="text-xs font-medium text-gray-600 flex-shrink-0">对比</span>

            {/* 左图下拉 */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-gray-400 flex-shrink-0">左</span>
              <select
                value={left.name}
                onChange={e => {
                  const f = comparableImages.find(x => x.name === e.target.value)
                  if (f) setLeftFile(f)
                }}
                className="text-[11px] border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 max-w-[130px] truncate focus:outline-none focus:border-blue-300"
              >
                {comparableImages.map(f => (
                  <option key={f.name} value={f.name}>{f.name}</option>
                ))}
              </select>
            </div>

            <ArrowLeftRight className="h-3 w-3 text-gray-300 flex-shrink-0" />

            {/* 右图下拉 */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-gray-400 flex-shrink-0">右</span>
              <select
                value={right.name}
                onChange={e => {
                  const f = comparableImages.find(x => x.name === e.target.value)
                  if (f) setRightFile(f)
                }}
                className="text-[11px] border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 max-w-[130px] truncate focus:outline-none focus:border-blue-300"
              >
                {comparableImages.map(f => (
                  <option key={f.name} value={f.name}>{f.name}</option>
                ))}
              </select>
            </div>
          </div>

          <button
            onClick={() => setCompareMode(false)}
            className="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 rounded transition-colors flex-shrink-0"
          >
            退出对比
          </button>
        </div>

        {/* 卷帘画布 */}
        <div className="flex-1 min-h-0">
          <CompareSlider
            srcBefore={leftUrl}
            srcAfter={rightUrl}
            labelBefore={leftName}
            labelAfter={rightName}
          />
        </div>

        {/* 底部文件名 */}
        <div className="px-3 py-1.5 border-t border-gray-100 flex items-center gap-3 text-xs text-gray-400">
          <span className="truncate">← {leftName}</span>
          <span className="flex-shrink-0">|</span>
          <span className="truncate">{rightName} →</span>
        </div>
      </div>
    )
  }

  // ── 常规单文件预览模式 ──
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
              key={f.path || f.name}
              onClick={() => { setActiveFile(f); setCompareMode(false); onFileClick?.(f) }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs whitespace-nowrap transition-colors flex-shrink-0 ${
                isActive
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : 'text-gray-500 hover:bg-gray-50 border border-transparent'
              }`}
            >
              <TabIcon cat={c} />
              <span className="max-w-[200px] truncate">{f.name}</span>
            </button>
          )
        })}
      </div>

      {/* 画布查看区 */}
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
