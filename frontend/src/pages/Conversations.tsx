import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Plus, Trash2, MessageSquare, Loader2, Activity, GripVertical, PanelLeftClose, PanelLeft } from 'lucide-react'
import { useAppStore } from '../stores/appStore'
import { useSessionState } from '../hooks/useSessionState'
import { conversationsApi } from '../api/conversations'
import { ChatPanel } from '../components/chat/ChatPanel'
import { CanvasPanel } from '../components/chat/CanvasPanel'
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
        files.push({
          name: String(f.name),
          path: String(f.path || f.name),
          relative_path: f.relative_path ? String(f.relative_path) : undefined,
          size: Number(f.size || 0),
          modified: String(f.modified || new Date().toISOString()),
        })
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
  // 从 conversations 列表中获取当前会话的状态
  const conversationStatus = conversations.find(c => c.id === convId)?.status
  // 使用 sessionStorage 持久化，切换页面后状态不丢失
  const sessionKey = convId ? `conv_${convId}` : null
  const [localMessages, setLocalMessages] = useSessionState<Message[]>(sessionKey ? `${sessionKey}_msgs` : 'conv_null_msgs', [])
  const [outputFiles, setOutputFiles] = useSessionState<OutputFile[]>(sessionKey ? `${sessionKey}_files` : 'conv_null_files', [])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const [recoveringToolName, setRecoveringToolName] = useState<string | null>(null)
  const [recoveringStepNumber, setRecoveringStepNumber] = useState<number | null>(null)
  // 工具步骤仅在执行中或恢复中显示，其他情况一律隐藏
  const isTaskRunning = conversationStatus === 'processing' || recovering
  const hideTools = !isTaskRunning
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastMsgIdRef = useRef<number>(0)

  // 侧边栏折叠状态（sessionStorage 持久化）
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { const s = sessionStorage.getItem('sidebar_collapsed'); return s === 'true' } catch { return false }
  })

  // 侧边栏可拖拽宽度（sessionStorage 持久化，默认 260px，范围 200-400）
  const SIDEBAR_MIN = 200
  const SIDEBAR_MAX = 400
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try { const s = sessionStorage.getItem('sidebar_width'); return s ? parseInt(s) : 260 } catch { return 260 }
  })
  const sidebarWidthRef = useRef(sidebarWidth)
  sidebarWidthRef.current = sidebarWidth
  const sidebarDragStartX = useRef(0)
  const sidebarDragStartW = useRef(0)
  const handleSidebarDragStart = useCallback((e: React.MouseEvent) => {
    if (sidebarCollapsed) return
    sidebarDragStartX.current = e.clientX
    sidebarDragStartW.current = sidebarWidthRef.current
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - sidebarDragStartX.current
      const w = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, sidebarDragStartW.current + delta))
      sidebarWidthRef.current = w
      setSidebarWidth(w)
    }
    const onUp = () => {
      try { sessionStorage.setItem('sidebar_width', String(sidebarWidthRef.current)) } catch {}
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [sidebarCollapsed])

  // 画布可拖拽宽度
  const CANVAS_MIN = 320
  const CANVAS_MAX_PCT = 0.6
  const [canvasWidth, setCanvasWidth] = useState(() => {
    try { const s = sessionStorage.getItem('canvas_width'); return s ? parseInt(s) : 420 } catch { return 420 }
  })
  const canvasWidthRef = useRef(canvasWidth)
  canvasWidthRef.current = canvasWidth
  const dragStartX = useRef(0)
  const dragStartW = useRef(0)
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    dragStartX.current = e.clientX
    dragStartW.current = canvasWidthRef.current
    const onMove = (ev: MouseEvent) => {
      const delta = dragStartX.current - ev.clientX
      const maxW = Math.floor(Math.max(CANVAS_MIN, (window.innerWidth - (sidebarCollapsed ? 40 : sidebarWidthRef.current + 6) - 6) * CANVAS_MAX_PCT))
      const w = Math.min(maxW, Math.max(CANVAS_MIN, dragStartW.current + delta))
      canvasWidthRef.current = w
      setCanvasWidth(w)
    }
    const onUp = () => {
      try { sessionStorage.setItem('canvas_width', String(canvasWidthRef.current)) } catch {}
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [sidebarCollapsed])

  // 从消息列表中提取最后的 tool_call 步骤信息
  const extractRecoveringStep = useCallback((messages: Message[]) => {
    let lastToolName: string | null = null
    let lastStepNumber: number | null = null
    // 从后往前找到最后一条 tool_call 消息
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'tool_call') {
        lastToolName = messages[i].tool_name || null
        lastStepNumber = messages[i].step_number ?? null
        break
      }
    }
    // 如果没有 tool_call 消息，尝试从所有消息中取最大 step_number
    if (lastStepNumber === null) {
      let maxStep = 0
      for (const msg of messages) {
        if (msg.step_number !== undefined && msg.step_number !== null && msg.step_number > maxStep) {
          maxStep = msg.step_number
        }
      }
      if (maxStep > 0) lastStepNumber = maxStep
    }
    setRecoveringToolName(lastToolName)
    setRecoveringStepNumber(lastStepNumber)
  }, [])

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
            // 合并消息，避免覆盖本地已有消息
            setLocalMessages(prev => {
              const merged = [...prev]
              for (const msg of result.messages) {
                if (!merged.some(m => m.id === msg.id)) {
                  merged.push(msg)
                }
              }
              return merged.sort((a, b) => a.id - b.id)
            })
            const files: OutputFile[] = []
            for (const msg of result.messages) {
              if (msg.tool_result) files.push(...extractFilesFromResult(msg.tool_result as Record<string, unknown>))
            }
            setOutputFiles(prev => { const ex = new Set(prev.map(f => f.name)); const nf = files.filter(f => !ex.has(f.name)); return nf.length > 0 ? [...prev, ...nf] : prev })
            if (lastMsg.role === 'assistant') { setRecovering(false); setRecoveringToolName(null); setRecoveringStepNumber(null); stopPolling(); fetchConversations(true) }
            else extractRecoveringStep(result.messages)
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
      setOutputFiles(files)
      if (result.messages.length > 0) lastMsgIdRef.current = result.messages[result.messages.length - 1].id
      if (convDetail.status === 'processing') {
        extractRecoveringStep(result.messages)
        setRecovering(true)
        startPolling(cId)
      } else { setRecovering(false); stopPolling() }
    } catch { /* 加载失败不清空已有消息 */ }
    finally { setLoadingMessages(false) }
  }, [startPolling, stopPolling])

  useEffect(() => { return () => stopPolling() }, [stopPolling])

  useEffect(() => {
    if (convId) {
      setActiveConversation(convId)
      lastMsgIdRef.current = 0
      stopPolling()
      loadMessages(convId)
    } else {
      // 切换到列表页时不强制清空——数据由 sessionStorage 保留，返回时恢复
      setRecovering(false)
      setRecoveringToolName(null)
      setRecoveringStepNumber(null)
      stopPolling()
    }
  }, [convId, loadMessages, setActiveConversation, stopPolling])

  const handleNew = async () => { const nid = await createConversation(); if (nid) navigate(`/conversations/${nid}`) }
  const handleDelete = async (cid: number) => { await deleteConversation(cid); if (convId === cid) navigate('/conversations') }
  const handleNewMsg = (msg: Message) => {
    setLocalMessages(p => {
      // 如果是 SSE 生成的 assistant 消息（id 为 Date.now() 的大数值），
      // 先不移除旧的，等 API 重新加载后用 DB 权威数据替换
      if (p.some(m => m.id === msg.id && m.role === msg.role)) return p
      return [...p, msg]
    })
    // 收到 assistant 消息说明任务完成，刷新会话状态 + 延迟加载最终结果
    if (msg.role === 'assistant' && convId) {
      fetchConversations(true)
      setTimeout(async () => {
        try {
          const result = await conversationsApi.getMessages(convId, 100)
          // 直接用 DB 权威消息替换，避免 SSE 临时消息（Date.now() ID）与 DB 消息重复
          setLocalMessages(result.messages)
          // 从 DB 消息提取文件，按文件名去重
          const files: OutputFile[] = []
          const seenNames = new Set<string>()
          for (const m of result.messages) {
            if (m.tool_result) {
              for (const f of extractFilesFromResult(m.tool_result as Record<string, unknown>)) {
                if (!seenNames.has(f.name)) {
                  seenNames.add(f.name)
                  files.push(f)
                }
              }
            }
          }
          setOutputFiles(files)
        } catch { /* ignore */ }
      }, 1200)
    }
  }
  const handleToolResult = (call: ToolCall) => {
    const files = extractFilesFromResult(call.result)
    if (files.length > 0) setOutputFiles(p => { const ex = new Set(p.map(f => f.name)); const nf = files.filter(f => !ex.has(f.name)); return nf.length > 0 ? [...p, ...nf] : p })
  }

  const handleSendStart = useCallback(() => { fetchConversations(true) }, [fetchConversations])
  const handleCancel = useCallback(() => { stopPolling(); setRecovering(false); setRecoveringToolName(null); setRecoveringStepNumber(null) }, [stopPolling])

  return (
    <div className="flex h-full bg-gray-50 overflow-hidden">
      {/* 侧边栏 */}
      {sidebarCollapsed ? (
        <div className="flex-shrink-0 border-r border-gray-200 bg-white flex flex-col items-center py-2" style={{ width: 40 }}>
          <button
            onClick={() => { setSidebarCollapsed(false); try { sessionStorage.setItem('sidebar_collapsed', 'false') } catch {} }}
            className="p-1.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600 transition-colors mt-1"
            title="展开侧边栏"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <div className="flex-1 flex items-center justify-center py-4">
            <span className="text-xs text-gray-400 font-medium tracking-widest select-none" style={{ writingMode: 'vertical-rl' }}>OpenGIS</span>
          </div>
        </div>
      ) : (
        <div className="flex-shrink-0 border-r border-gray-200 bg-white flex flex-col relative group/sidebar" style={{ width: sidebarWidth, minWidth: SIDEBAR_MIN }}>
          {/* 标题栏：折叠按钮 + 新建按钮 */}
          <div className="p-3 border-b border-gray-100 flex items-center gap-2">
            <button onClick={handleNew} className="flex items-center justify-center gap-2 flex-1 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors">
              <Plus className="h-4 w-4" />新对话
            </button>
            <button
              onClick={() => { setSidebarCollapsed(true); try { sessionStorage.setItem('sidebar_collapsed', 'true') } catch {} }}
              className="p-1.5 hover:bg-gray-100 rounded text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
              title="折叠侧边栏"
            >
              <PanelLeftClose className="h-4 w-4" />
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
      )}

      {/* 侧边栏拖拽手柄（仅在展开状态下可用） */}
      {!sidebarCollapsed && (
        <div
          className="w-1.5 hover:w-2 cursor-col-resize bg-transparent hover:bg-blue-200 transition-colors flex-shrink-0 relative group flex items-center justify-center"
          onMouseDown={handleSidebarDragStart}
        >
          <GripVertical className="h-5 w-5 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
        </div>
      )}

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
                  <span className="text-xs text-blue-600">
                    Agent 正在执行中，自动恢复连接...
                    {recoveringStepNumber && (
                      <span className="ml-1">当前步骤: 步骤 {recoveringStepNumber}{recoveringToolName ? ` - ${recoveringToolName}` : ''}</span>
                    )}
                  </span>
                </div>
              )}
              <ChatPanel key={convId} convId={convId} messages={localMessages} onNewMessage={handleNewMsg} onToolResult={handleToolResult} onSendStart={handleSendStart} onCancel={handleCancel} hideTools={hideTools} />
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

      {/* 拖拽手柄 */}
      {convId && (
        <div
          className="w-1.5 hover:w-2 cursor-col-resize bg-transparent hover:bg-blue-200 transition-colors flex-shrink-0 relative group flex items-center justify-center"
          onMouseDown={handleDragStart}
        >
          <GripVertical className="h-5 w-5 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
        </div>
      )}

      {/* 画布面板 */}
      {convId ? (
        <div className="border-l border-gray-200 bg-white flex flex-col" style={{ width: canvasWidth, minWidth: CANVAS_MIN, flexShrink: 1 }}>
          <CanvasPanel files={outputFiles} />
        </div>
      ) : null}
    </div>
  )
}
