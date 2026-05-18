/**
 * OpenGIS 工作空间 — 展示区（手风琴式对话浏览 + 画布预览）
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ChevronRight, ChevronDown, Trash2, FileImage, FileText,
  MessageSquare, Activity, Terminal, Sparkles, Image as ImageIcon,
  Film, X, Maximize2, Minimize2
} from 'lucide-react'
import { useAppStore, type OutputFile } from '../stores/appStore'
import { conversationsApi } from '../api/conversations'
import ViewerRouter from '../components/ViewerRouter'

// ── 工具函数 ──
function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-stone-900">$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="bg-stone-100 text-stone-700 px-1.5 py-0.5 rounded text-xs font-mono">$1</code>')
    .replace(/^### (.+)$/gm, '<h4 class="text-sm font-semibold text-stone-800 mt-3 mb-1">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="text-sm font-semibold text-stone-900 mt-4 mb-1">$1</h3>')
    .replace(/^[-*] (.+)$/gm, '<li class="ml-3 text-sm text-stone-600">• $1</li>')
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
  return html
}

function extractFilesFromResult(result: Record<string, unknown> | undefined): OutputFile[] {
  if (!result || !result.success) return []
  const files: OutputFile[] = []
  const keys = ['output_png', 'output_tif', 'output_gif', 'output_html', 'output_csv']
  for (const key of keys) {
    const path = result[key]
    if (typeof path === 'string' && path) {
      const name = path.replace(/\\/g, '/').split('/').pop() || path
      if (name) files.push({ name, path, size: 0, modified: new Date().toISOString() })
    }
  }
  const of = result.output_files
  if (Array.isArray(of)) {
    for (const f of of) {
      if (f && typeof f === 'object' && f.name) {
        files.push({ name: String(f.name), path: String(f.path || f.name), size: Number(f.size || 0), modified: String(f.modified || new Date().toISOString()) })
      }
    }
  }
  return files
}

function formatTime(iso: string) {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString()
}

const isGifFile = (name: string) => name.endsWith('.gif')
const isImageFile = (name: string) => /\.(png|jpg|jpeg|tif|tiff)$/i.test(name)
const isTifFile = (name: string) => /\.(tif|tiff)$/i.test(name)
const isHtmlFile = (name: string) => name.endsWith('.html')

// ── 消息气泡组件 ──
function MessageBubble({ msg }: { msg: any }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[80%] bg-emerald-600 text-white rounded-2xl rounded-br-md px-4 py-2.5">
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
          <p className="text-[10px] mt-1.5 text-emerald-200">
            {new Date(msg.created_at).toLocaleTimeString()}
          </p>
        </div>
      </div>
    )
  }

  if (msg.role === 'assistant') {
    return (
      <div className="flex justify-start mb-3">
        <div className="max-w-[85%] bg-stone-100 text-stone-800 rounded-2xl rounded-bl-md px-4 py-2.5">
          <div
            className="text-sm leading-relaxed"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
          />
          <p className="text-[10px] mt-1.5 text-stone-400">
            {new Date(msg.created_at).toLocaleTimeString()}
          </p>
        </div>
      </div>
    )
  }

  if (msg.role === 'tool_call') {
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[85%] bg-blue-50 text-blue-700 border border-blue-200 rounded-xl rounded-bl-md px-3 py-2">
          <div className="flex items-center gap-2">
            <Terminal className="h-3.5 w-3.5 flex-shrink-0" />
            <span className="text-xs font-medium">{msg.tool_name || '工具调用'}</span>
          </div>
          {msg.content && (
            <p className="text-xs mt-1 text-blue-600">{msg.content}</p>
          )}
        </div>
      </div>
    )
  }

  if (msg.role === 'tool_result') {
    const files = extractFilesFromResult(msg.tool_result as Record<string, unknown>)
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[85%] bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-xl rounded-bl-md px-3 py-2">
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="h-3.5 w-3.5 flex-shrink-0" />
            <span className="text-xs font-medium">{msg.tool_name || '工具结果'}</span>
          </div>
          {msg.content && (
            <p className="text-xs text-emerald-600 line-clamp-3">{msg.content}</p>
          )}
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {files.map(f => (
                <span key={f.name} className="text-[10px] px-1.5 py-0.5 bg-emerald-100 rounded">
                  {f.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return null
}

// ── 对话卡片组件 ──
function ConversationCard({
  conv,
  isExpanded,
  onToggle,
  onDelete,
  messages,
  onFileClick,
  previewFile
}: {
  conv: any
  isExpanded: boolean
  onToggle: () => void
  onDelete: (e: React.MouseEvent) => void
  messages: any[] | null
  onFileClick: (file: OutputFile) => void
  previewFile: OutputFile | null
}) {
  // 提取所有输出文件
  const allFiles = messages
    ?.filter(m => m.tool_result)
    .flatMap(m => extractFilesFromResult(m.tool_result as Record<string, unknown>))
    .filter((f, i, arr) => arr.findIndex(x => x.name === f.name) === i) || []

  return (
    <div className="border border-stone-200 rounded-xl overflow-hidden bg-white mb-3 shadow-sm">
      {/* 头部 - 始终显示 */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-stone-50 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className="flex-shrink-0">
            {conv.status === 'processing' ? (
              <Activity className="h-4 w-4 text-emerald-500 animate-pulse" />
            ) : (
              <MessageSquare className="h-4 w-4 text-stone-400" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-medium text-stone-800 truncate">
              {conv.title || '新对话'}
            </h3>
            <p className="text-[11px] text-stone-400 mt-0.5">
              {formatTime(conv.updated_at)}
              {allFiles.length > 0 && ` · ${allFiles.length} 个结果`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={e => { e.stopPropagation(); onDelete(e) }}
            className="p-1 text-stone-400 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-stone-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-stone-400" />
          )}
        </div>
      </div>

      {/* 展开内容 - 对话消息 + 结果文件 */}
      {isExpanded && messages && (
        <div className="border-t border-stone-100">
          {/* 消息列表 */}
          <div className="max-h-[500px] overflow-y-auto p-4 space-y-1">
            {messages.map((msg, idx) => (
              <MessageBubble key={msg.id || idx} msg={msg} />
            ))}
          </div>

          {/* 结果文件区 */}
          {allFiles.length > 0 && (
            <div className="border-t border-stone-100 px-4 py-3 bg-stone-50">
              <p className="text-xs font-medium text-stone-500 mb-2">输出结果</p>
              <div className="flex flex-wrap gap-2">
                {allFiles.map(f => {
                  const isActive = previewFile?.name === f.name
                  return (
                    <button
                      key={f.name}
                      onClick={() => onFileClick(f)}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                        isActive
                          ? 'bg-emerald-100 text-emerald-700 border border-emerald-300'
                          : 'bg-white text-stone-600 border border-stone-200 hover:border-emerald-300 hover:text-emerald-600'
                      }`}
                    >
                      {isImageFile(f.name) ? (
                        <ImageIcon className="h-3.5 w-3.5" />
                      ) : isGifFile(f.name) ? (
                        <Film className="h-3.5 w-3.5" />
                      ) : isHtmlFile(f.name) ? (
                        <FileText className="h-3.5 w-3.5" />
                      ) : (
                        <FileImage className="h-3.5 w-3.5" />
                      )}
                      <span className="truncate max-w-[120px]">{f.name}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 加载状态 */}
          {!messages && (
            <div className="px-4 py-6 text-center">
              <p className="text-sm text-stone-400">加载中...</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── 主组件 ──
export default function Workspace() {
  const navigate = useNavigate()

  // 状态
  const [expandedConvId, setExpandedConvId] = useState<number | null>(null)
  const [convMessages, setConvMessages] = useState<Record<number, any[]>>({})
  const [previewFile, setPreviewFile] = useState<OutputFile | null>(null)
  const [fullscreenPreview, setFullscreenPreview] = useState(false)

  const {
    conversations, fetchConversations, deleteConversation
  } = useAppStore()

  // ── 初始化 ──
  useEffect(() => { fetchConversations() }, [fetchConversations])

  // ── 切换展开/折叠 ──
  const toggleConv = useCallback(async (cid: number) => {
    if (expandedConvId === cid) {
      // 收起当前
      setExpandedConvId(null)
      setPreviewFile(null)
    } else {
      // 展开新的，自动收起其他的
      setExpandedConvId(cid)
      setPreviewFile(null)

      // 如果没有加载过消息，加载
      if (!convMessages[cid]) {
        try {
          const result = await conversationsApi.getMessages(cid, 200)
          setConvMessages(prev => ({ ...prev, [cid]: result.messages }))
        } catch (err) {
          console.error('加载消息失败:', err)
        }
      }
    }
  }, [expandedConvId, convMessages])

  // ── 删除对话 ──
  const handleDelete = useCallback(async (cid: number) => {
    await deleteConversation(cid)
    if (expandedConvId === cid) {
      setExpandedConvId(null)
      setPreviewFile(null)
    }
  }, [expandedConvId, deleteConversation])

  // ── 点击结果文件 ──
  const handleFileClick = useCallback((file: OutputFile) => {
    setPreviewFile(file)
  }, [])

  // ── 获取预览 URL ──
  const getPreviewUrl = useCallback((file: OutputFile) => {
    if (expandedConvId && isTifFile(file.name)) {
      return `/api/conversations/${expandedConvId}/preview/${encodeURIComponent(file.name)}`
    }
    return `/outputs/${encodeURIComponent(file.name)}`
  }, [expandedConvId])

  return (
    <div className="h-[calc(100vh-56px)] flex overflow-hidden bg-stone-50">
      {/* ── 左侧：对话列表区 ── */}
      <div className="w-[480px] min-w-[400px] flex-shrink-0 flex flex-col border-r border-stone-200 bg-white">
        {/* 头部 */}
        <div className="px-4 py-3 border-b border-stone-100">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-emerald-100 flex items-center justify-center">
              <Terminal className="h-3.5 w-3.5 text-emerald-600" />
            </div>
            <h2 className="font-semibold text-stone-800 text-sm">工作空间 — 对话记录</h2>
          </div>
          <p className="text-[11px] text-stone-400 mt-1">
            点击展开查看完整对话内容和结果
          </p>
        </div>

        {/* 对话列表 */}
        <div className="flex-1 overflow-y-auto p-4">
          {conversations.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-12 h-12 rounded-xl bg-stone-100 flex items-center justify-center mx-auto mb-3">
                <MessageSquare className="h-6 w-6 text-stone-400" />
              </div>
              <p className="text-sm text-stone-500">暂无对话记录</p>
              <button
                onClick={() => navigate('/chat')}
                className="mt-3 text-xs text-emerald-600 hover:text-emerald-700"
              >
                去对话页面开始新对话 →
              </button>
            </div>
          ) : (
            conversations.map(conv => (
              <ConversationCard
                key={conv.id}
                conv={conv}
                isExpanded={expandedConvId === conv.id}
                onToggle={() => toggleConv(conv.id)}
                onDelete={(e) => { e.stopPropagation(); handleDelete(conv.id) }}
                messages={convMessages[conv.id] || null}
                onFileClick={handleFileClick}
                previewFile={previewFile}
              />
            ))
          )}
        </div>
      </div>

      {/* ── 右侧：画布预览区 ── */}
      <div className="flex-1 flex flex-col bg-stone-100">
        {previewFile ? (
          <>
            {/* 预览头部 */}
            <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-stone-200">
              <div className="flex items-center gap-2">
                {isImageFile(previewFile.name) ? (
                  <ImageIcon className="h-4 w-4 text-stone-500" />
                ) : isGifFile(previewFile.name) ? (
                  <Film className="h-4 w-4 text-stone-500" />
                ) : (
                  <FileText className="h-4 w-4 text-stone-500" />
                )}
                <span className="text-sm font-medium text-stone-700">{previewFile.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setFullscreenPreview(!fullscreenPreview)}
                  className="p-1.5 text-stone-400 hover:text-stone-600 transition-colors"
                >
                  {fullscreenPreview ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                </button>
                <button
                  onClick={() => setPreviewFile(null)}
                  className="p-1.5 text-stone-400 hover:text-stone-600 transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* 预览内容 */}
            <div className={`flex-1 overflow-auto ${fullscreenPreview ? 'p-0' : 'p-6'}`}>
              <div className={`${fullscreenPreview ? 'h-full' : 'max-w-4xl mx-auto'}`}>
                <ViewerRouter
                  file={previewFile}
                  src={getPreviewUrl(previewFile)}
                />
              </div>
            </div>
          </>
        ) : (
          /* 空状态 */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 rounded-2xl bg-stone-200 flex items-center justify-center mx-auto mb-4">
                <FileImage className="h-8 w-8 text-stone-400" />
              </div>
              <h3 className="text-lg font-medium text-stone-600 mb-2">结果预览</h3>
              <p className="text-sm text-stone-400">
                在左侧展开对话，点击结果文件即可在此预览
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
