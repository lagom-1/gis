import { useState } from 'react'
import { ExternalLink, RefreshCw, Globe } from 'lucide-react'

interface HtmlPreviewProps {
  src: string
  filename: string
}

export default function HtmlPreview({ src, filename }: HtmlPreviewProps) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [iframeKey, setIframeKey] = useState(0)

  // 加载 HTML 为 blob URL 以便 iframe 使用
  useState(() => {
    fetch(src)
      .then(r => r.text())
      .then(html => {
        const blob = new Blob([html], { type: 'text/html' })
        const url = URL.createObjectURL(blob)
        setBlobUrl(url)
        setLoading(false)
      })
      .catch(() => {
        setError(true)
        setLoading(false)
      })
  })

  const handleRefresh = () => {
    setLoading(true)
    setIframeKey(k => k + 1)
    setLoading(false)
  }

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="bg-white border-b px-4 py-2 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center space-x-2">
          <Globe className="h-4 w-4 text-blue-600" />
          <span className="text-sm font-medium text-gray-700">交互地图预览</span>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={handleRefresh}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
            title="刷新"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <a
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center space-x-1 text-xs text-primary-600 hover:text-primary-700 px-2 py-1 bg-primary-50 hover:bg-primary-100 rounded transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
            <span>新窗口打开</span>
          </a>
        </div>
      </div>

      {/* iframe 内容 */}
      <div className="flex-1 bg-white min-h-0">
        {loading && !error && (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            加载中...
          </div>
        )}
        {error && (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm">
            无法加载 HTML，请
            <a href={src} target="_blank" rel="noopener noreferrer" className="text-primary-600 ml-1">在新窗口打开</a>
          </div>
        )}
        {blobUrl && (
          <iframe
            key={iframeKey}
            src={blobUrl}
            title={filename}
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin"
            onLoad={() => setLoading(false)}
          />
        )}
      </div>
    </div>
  )
}
