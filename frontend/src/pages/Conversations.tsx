import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Plus, Trash2, MessageSquare, Loader2, Activity } from 'lucide-react'
import { useAppStore } from '../stores/appStore'
import { conversationsApi } from '../api/conversations'
import { ChatPanel } from '../components/chat/ChatPanel'
import { OutputPanel } from '../components/chat/OutputPanel'
import type { Message, OutputFile, ToolCall } from '../types/conversation'

function extractFilesFromResult(result: Record<string, unknown> | undefined): OutputFile[] {
  if (!result || !result.success) return []
  const files: OutputFile[] = []
  const keys = ['output_png', 'output_tif', 'output_gif', 'output_html', 'output_csv']
  for (const key of keys) {
    const path = result[key]
    if (typeof path === 'string' && path) {
      const name = path.replace(/\\/g, '/').split('/').pop() || path
      if (name) files.push({ name, path: path as string, size: 0, modified: new Date().toISOString() })
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

export default function Conversations() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const convId = id ? parseInt(id) : null

  const { conversations, isLoadingConversations, fetchConversations, createConversation, deleteConversation, setActiveConversation } = useAppStore()
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastMsgIdRef = useRef<number>(0)

  useEffect(() => { fetchConversations() }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const startPolling = useCallback((cId: number) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const result = await conversationsApi.getMessages(cId, 100)
        if (result.messages.length > 0) {
          const lastMsg = result.messages[result.messages.length - 1]
          if (lastMsg.id > lastMsgIdRef.current) {
            lastMsgIdRef.current = lastMsg.id
            setLocalMessages(result.messages)
            const files: OutputFile[] = []
            for (const msg of result.messages) {
              if (msg.tool_result) files.push(...extractFilesFromResult(msg.tool_result as Record<string, unknown>))
            }
            setOutputFiles(prev => { const ex = new Set(prev.map(f => f.name)); const nf = files.filter(f => !ex.has(f.name)); return nf.length > 0 ? [...prev, ...nf] : prev })
            if (lastMsg.role === 'assistant') { setRecovering(false); stopPolling(); fetchConversations(true) }
          }
        }
      } catch { /* retry */ }
    }, 2000)
  }, [fetchConversations, stopPolling])

  const loadMessages = useCallback(async (cId: number) => {
    setLoadingMessages(true)
    try {
      const [result, convDetail] = await Promise.all([
        conversationsApi.getMessages(cId, 100),
        conversationsApi.get(cId),
      ])
      setLocalMessages(result.messages)
      const files: OutputFile[] = []
      for (const msg of result.messages) { if (msg.tool_result) files.push(...extractFilesFromResult(msg.tool_result as Record<string, unknown>)) }
      setOutputFiles(prev => { const ex = new Set(prev.map(f => f.name)); const nf = files.filter(f => !ex.has(f.name)); return nf.length > 0 ? [...prev, ...nf] : prev })
      if (result.messages.length > 0) lastMsgIdRef.current = result.messages[result.messages.length - 1].id
      if (convDetail.status === 'processing') { setRecovering(true); startPolling(cId) }
      else { setRecovering(false); stopPolling() }
    } catch { setLocalMessages([]) }
    finally { setLoadingMessages(false) }
  }, [startPolling, stopPolling])

  useEffect(() => { return () => stopPolling() }, [stopPolling])

  useEffect(() => {
    if (convId) { setActiveConversation(convId); setOutputFiles([]); lastMsgIdRef.current = 0; stopPolling(); loadMessages(convId) }
    else { setLocalMessages([]); setOutputFiles([]); setRecovering(false); stopPolling() }
  }, [convId, loadMessages, setActiveConversation, stopPolling])

  const handleNew = async () => { const nid = await createConversation(); if (nid) navigate(`/conversations/${nid}`) }
  const handleDelete = async (cid: number) => { await deleteConversation(cid); if (convId === cid) navigate('/conversations') }
  const handleNewMsg = (msg: Message) => { setLocalMessages(p => p.some(m => m.id === msg.id && m.role === msg.role) ? p : [...p, msg]) }
  const handleToolResult = (call: ToolCall) => {
    const files = extractFilesFromResult(call.result)
    if (files.length > 0) setOutputFiles(p => { const ex = new Set(p.map(f => f.name)); const nf = files.filter(f => !ex.has(f.name)); return nf.length > 0 ? [...p, ...nf] : p })
  }

  return (
    <div className="flex h-[calc(100vh-56px)] bg-gray-50">
      {/* 侧边栏 */}
      <div className="w-64 border-r border-gray-200 bg-white flex flex-col flex-shrink-0">
        <div className="p-3 border-b border-gray-100">
          <button onClick={handleNew} className="flex items-center justify-center gap-2 w-full py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors">
            <Plus className="h-4 w-4" />新对话
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {isLoadingConversations ? (
            <div className="p-4 text-center"><Loader2 className="h-4 w-4 animate-spin text-gray-400 mx-auto" /></div>
          ) : conversations.length === 0 ? (
            <div className="p-6 text-center text-sm text-gray-400">暂无对话</div>
          ) : conversations.map(conv => (
            <button key={conv.id} onClick={() => navigate(`/conversations/${conv.id}`)}
              className={`w-full text-left p-3 border-b border-gray-50 hover:bg-gray-50 transition-colors group ${conv.id === convId ? 'bg-blue-50 border-l-2 border-l-blue-500' : 'border-l-2 border-l-transparent'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  {conv.status === 'processing' ? <Activity className="h-3.5 w-3.5 text-blue-500 animate-pulse flex-shrink-0" /> : <MessageSquare className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />}
                  <div className="min-w-0 flex-1">
                    <span className="text-sm text-gray-700 truncate block">{conv.title || '新对话'}</span>
                    <div className="flex items-center gap-2 mt-0.5">
                      {conv.status === 'processing' && <span className="text-xs text-blue-500 font-medium">执行中</span>}
                      <span className="text-xs text-gray-400">{formatTime(conv.updated_at)}</span>
                    </div>
                  </div>
                </div>
                <button onClick={e => { e.stopPropagation(); handleDelete(conv.id) }} className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 对话区 */}
      <div className="flex-1 flex flex-col min-w-0 bg-white border-x border-gray-200">
        {convId ? (
          loadingMessages ? (
            <div className="flex-1 flex items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-gray-400 mr-2" /><span className="text-sm text-gray-400">加载消息...</span></div>
          ) : (
            <>
              {recovering && (
                <div className="bg-blue-50 border-b border-blue-100 px-4 py-2 flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />
                  <span className="text-xs text-blue-600">Agent 正在执行中，自动恢复连接...</span>
                </div>
              )}
              <ChatPanel convId={convId} messages={localMessages} onNewMessage={handleNewMsg} onToolResult={handleToolResult} onSendStart={() => fetchConversations(true)} onCancel={() => { stopPolling(); setRecovering(false) }} />
            </>
          )
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p className="text-base font-medium text-gray-500 mb-4">选择或创建一个对话开始</p>
              <button onClick={handleNew} className="px-5 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors">开始新对话</button>
            </div>
          </div>
        )}
      </div>

      {/* 输出面板 */}
      <OutputPanel files={outputFiles} onFileClick={(f) => window.open(`/outputs/${encodeURIComponent(f.name)}`, '_blank')} />
    </div>
  )
}
