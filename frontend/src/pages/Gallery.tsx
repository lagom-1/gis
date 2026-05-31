import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ImageIcon, Film, FileText, Table2, ExternalLink, X } from 'lucide-react'
import { useAppStore } from '../stores/appStore'
import { conversationsService } from '../services/conversations'
import type { OutputFile } from '../types/conversation'
import ViewerRouter from '../components/ViewerRouter'
import { extractFilesFromResult, formatTime } from '../utils/workspace'

interface GalleryItem {
  file: OutputFile
  convId: number
  convTitle: string
  convDate: string
  category: string
}

function getCategory(name: string) {
  if (/\.gif$/i.test(name)) return 'gif'
  if (/\.html$/i.test(name)) return 'html'
  if (/\.csv$/i.test(name)) return 'csv'
  return 'image'
}

function getUrl(file: OutputFile) {
  const p = (file.path || file.name).replace(/\\/g, '/')
  const idx = p.lastIndexOf('/outputs/')
  const rel = idx >= 0 ? p.slice(idx + 1) : `outputs/${file.name}`
  return '/' + rel.split('/').map(encodeURIComponent).join('/')
}

const TYPE_FILTERS = [
  { key: 'all', label: '全部', icon: ImageIcon },
  { key: 'image', label: '图片', icon: ImageIcon },
  { key: 'gif', label: 'GIF', icon: Film },
  { key: 'csv', label: 'CSV', icon: Table2 },
  { key: 'html', label: 'HTML', icon: FileText },
]

export default function Gallery() {
  const navigate = useNavigate()
  const { conversations, fetchConversations } = useAppStore()
  const [items, setItems] = useState<GalleryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [preview, setPreview] = useState<{ file: OutputFile; src: string } | null>(null)

  useEffect(() => { fetchConversations() }, [fetchConversations])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const all: GalleryItem[] = []
      const seen = new Set<string>()

      for (const conv of conversations) {
        try {
          const result = await conversationsService.getMessages(conv.id, { limit: 200 })
          for (const msg of result.messages) {
            if (!msg.tool_result) continue
            const files = extractFilesFromResult(msg.tool_result as Record<string, unknown>)
            for (const f of files) {
              if (seen.has(f.path)) continue
              seen.add(f.path)
              all.push({
                file: f,
                convId: conv.id,
                convTitle: conv.title || '新对话',
                convDate: conv.updated_at,
                category: getCategory(f.name),
              })
            }
          }
        } catch { /* skip failed loads */ }
      }

      if (!cancelled) {
        all.sort((a, b) => new Date(b.convDate).getTime() - new Date(a.convDate).getTime())
        setItems(all)
        setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [conversations])

  const filtered = useMemo(() => {
    let result = items
    if (filter !== 'all') result = result.filter(i => i.category === filter)
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(i =>
        i.file.name.toLowerCase().includes(q) || i.convTitle.toLowerCase().includes(q)
      )
    }
    return result
  }, [items, filter, search])

  return (
    <div className="h-full overflow-hidden flex flex-col bg-stone-50">
      {/* 头部 */}
      <div className="bg-white border-b border-stone-200 px-6 py-4 flex-shrink-0">
        <h1 className="text-lg font-bold text-stone-800 mb-3">成果画廊</h1>
        <div className="flex items-center gap-3 flex-wrap">
          {/* 类型筛选 */}
          <div className="flex items-center gap-1">
            {TYPE_FILTERS.map(t => {
              const Icon = t.icon
              const active = filter === t.key
              return (
                <button
                  key={t.key}
                  onClick={() => setFilter(t.key)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    active
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'text-stone-500 hover:bg-stone-100'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t.label}
                </button>
              )
            })}
          </div>
          {/* 搜索 */}
          <div className="relative flex-1 max-w-xs ml-auto">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-stone-400" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索文件名或对话..."
              className="w-full pl-9 pr-3 py-1.5 text-xs border border-stone-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
            />
          </div>
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin h-6 w-6 border-2 border-emerald-500 border-t-transparent rounded-full" />
            <span className="ml-3 text-sm text-stone-400">加载中...</span>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <ImageIcon className="h-12 w-12 mx-auto mb-3 text-stone-300" />
              <p className="text-sm text-stone-500 mb-1">
                {items.length === 0 ? '暂无产出的文件' : '无匹配结果'}
              </p>
              <p className="text-xs text-stone-400">
                {items.length === 0 ? '前往对话页开始您的第一次 GIS 分析' : '尝试调整筛选条件'}
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
            {filtered.map(item => (
              <button
                key={item.file.path}
                onClick={() => setPreview({ file: item.file, src: getUrl(item.file) })}
                className="bg-white rounded-xl border border-stone-200 overflow-hidden hover:shadow-md hover:border-emerald-200 transition-all text-left group"
              >
                {/* 缩略图 */}
                <div className="aspect-[4/3] bg-stone-100 flex items-center justify-center overflow-hidden relative">
                  {item.category === 'image' ? (
                    <img
                      src={getUrl(item.file)}
                      alt={item.file.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-1 text-stone-400">
                      {item.category === 'gif' && <Film className="h-8 w-8" />}
                      {item.category === 'csv' && <Table2 className="h-8 w-8" />}
                      {item.category === 'html' && <FileText className="h-8 w-8" />}
                      <span className="text-[10px] font-medium">{item.file.name.split('.').pop()?.toUpperCase()}</span>
                    </div>
                  )}
                </div>
                {/* 信息 */}
                <div className="p-2.5">
                  <p className="text-xs font-medium text-stone-700 truncate" title={item.file.name}>
                    {item.file.name}
                  </p>
                  <div className="flex items-center justify-between mt-1">
                    <button
                      onClick={e => { e.stopPropagation(); navigate(`/conversations/${item.convId}`) }}
                      className="text-[11px] text-emerald-600 hover:text-emerald-700 truncate max-w-[70%] flex items-center gap-0.5"
                      title={item.convTitle}
                    >
                      {item.convTitle}
                      <ExternalLink className="h-2.5 w-2.5 flex-shrink-0" />
                    </button>
                    <span className="text-[10px] text-stone-400 flex-shrink-0">{formatTime(item.convDate)}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 灯箱预览 */}
      {preview && (
        <div className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center" onClick={() => setPreview(null)}>
          <button onClick={() => setPreview(null)} className="absolute top-4 right-4 p-2 text-white/60 hover:text-white z-10">
            <X className="h-6 w-6" />
          </button>
          <div className="w-full h-full p-8" onClick={e => e.stopPropagation()}>
            <ViewerRouter
              file={{ ...preview.file, relative_path: preview.file.path }}
              src={preview.src}
            />
          </div>
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-white/50">{preview.file.name}</div>
        </div>
      )}
    </div>
  )
}
