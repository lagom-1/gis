import { useState, useEffect } from 'react'
import {
  ImageIcon, FileImage, FileText, Film, Table2,
  Download, Maximize2, PanelRightClose, PanelRight, X,
} from 'lucide-react'
import type { OutputFile } from '../../types/conversation'

interface Props {
  files: OutputFile[]
  onFileClick?: (file: OutputFile) => void
}

function formatSize(bytes: number) {
  if (!bytes || bytes <= 0) return '--'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function isPreviewable(name: string) {
  return /\.(png|jpg|jpeg|gif|webp|svg|tif|tiff)$/i.test(name)
}

function getCategory(name: string) {
  if (/\.gif$/i.test(name)) return 'gif'
  if (/\.html$/i.test(name)) return 'html'
  if (/\.csv$/i.test(name)) return 'csv'
  return 'image'
}

function FileIcon({ cat }: { cat: string }) {
  const cls = "h-4 w-4 flex-shrink-0"
  switch (cat) {
    case 'gif': return <Film className={`${cls} text-emerald-500`} />
    case 'html': return <FileText className={`${cls} text-violet-500`} />
    case 'csv': return <Table2 className={`${cls} text-blue-500`} />
    default: return <FileImage className={`${cls} text-blue-500`} />
  }
}

export function OutputPanel({ files, onFileClick }: Props) {
  const [preview, setPreview] = useState<OutputFile | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [lightbox, setLightbox] = useState(false)

  useEffect(() => {
    if (files.length > 0 && !preview) {
      const img = files.find(f => isPreviewable(f.name))
      setPreview(img || files[0])
    }
  }, [files])

  const active = preview || (files.length > 0 ? files[0] : null)
  const getUrl = (f: OutputFile) => `/outputs/${encodeURIComponent(f.name)}`

  if (collapsed) {
    return (
      <div className="w-11 flex-shrink-0 border-l border-gray-200 bg-white flex flex-col items-center pt-4 gap-3">
        <button onClick={() => setCollapsed(false)} className="p-1.5 text-gray-400 hover:text-gray-600" title="展开">
          <PanelRight className="h-4 w-4" />
        </button>
        {files.length > 0 && <span className="text-xs font-semibold text-blue-500">{files.length}</span>}
      </div>
    )
  }

  return (
    <>
      <div className="w-[380px] min-w-[320px] flex-shrink-0 border-l border-gray-200 bg-white flex flex-col">
        <div className="border-b border-gray-100 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-gray-700">输出文件</h4>
            {files.length > 0 && (
              <span className="text-xs text-white bg-blue-500 px-1.5 py-0.5 rounded-full">{files.length}</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {active && isPreviewable(active.name) && (
              <button onClick={() => setLightbox(true)} className="p-1.5 text-gray-400 hover:text-gray-600 rounded" title="全屏">
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            )}
            <button onClick={() => setCollapsed(true)} className="p-1.5 text-gray-400 hover:text-gray-600 rounded" title="折叠">
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {files.length === 0 ? (
          <div className="flex-1 flex items-center justify-center p-6">
            <div className="text-center text-gray-400">
              <ImageIcon className="h-10 w-10 mx-auto mb-2 opacity-30" />
              <p className="text-sm">等待输出结果</p>
              <p className="text-xs mt-1">任务生成的文件将在这里展示</p>
            </div>
          </div>
        ) : (
          <>
            {active && isPreviewable(active.name) && (
              <div
                className="h-56 bg-gray-100 border-b border-gray-100 flex items-center justify-center cursor-pointer group relative"
                onClick={() => setLightbox(true)}
              >
                <img src={getUrl(active)} alt={active.name} className="max-h-full max-w-full object-contain"
                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
              </div>
            )}
            <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
              {files.map(f => {
                const cat = getCategory(f.name)
                const isActive = active?.name === f.name
                return (
                  <button
                    key={f.name}
                    onClick={() => { setPreview(f); onFileClick?.(f) }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left text-xs transition-colors group ${
                      isActive ? 'bg-blue-50 border border-blue-100' : 'border border-transparent hover:bg-gray-50'
                    }`}
                  >
                    <FileIcon cat={cat} />
                    <span className={`flex-1 truncate ${isActive ? 'font-medium text-gray-800' : 'text-gray-600'}`}>{f.name}</span>
                    <span className="text-gray-400 flex-shrink-0 text-[11px]">{formatSize(f.size)}</span>
                    <a href={getUrl(f)} download={f.name} onClick={e => e.stopPropagation()}
                      className="p-1 text-gray-300 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition-all">
                      <Download className="h-3 w-3" />
                    </a>
                  </button>
                )
              })}
            </div>
          </>
        )}

        {active && (
          <div className="border-t border-gray-100 px-4 py-2 flex items-center justify-between text-xs text-gray-400">
            <span className="truncate">{active.name}</span>
            <span>{formatSize(active.size)}</span>
          </div>
        )}
      </div>

      {lightbox && active && (
        <div className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center" onClick={() => setLightbox(false)}>
          <button onClick={() => setLightbox(false)} className="absolute top-4 right-4 p-2 text-white/60 hover:text-white">
            <X className="h-6 w-6" />
          </button>
          <img src={getUrl(active)} alt={active.name} className="max-h-[90vh] max-w-[90vw] object-contain" onClick={e => e.stopPropagation()} />
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-white/50">{active.name}</div>
        </div>
      )}
    </>
  )
}
