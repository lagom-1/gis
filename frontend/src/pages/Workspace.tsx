import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, Image as ImageIcon, Film, BarChart3, ChevronLeft, ChevronRight, Trash2, FileImage, FileText, Download, Maximize2, Minimize2, Cpu } from 'lucide-react'
import { useTaskStore } from '../stores/taskStore'
import { useWorkspaceStore, type OutputFile } from '../stores/workspaceStore'
import { tasksService } from '../services/tasks'
import ViewerRouter from '../components/ViewerRouter'
import CompareSlider from '../components/CompareSlider'
import toast from 'react-hot-toast'

// 已处理过的任务 ID 集合（模块级，跨挂载持久）
const processedTaskIds = new Set<number>()

// 简单的 Markdown 渲染
function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-gray-900">$1</strong>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code class="bg-gray-200 text-gray-800 px-1 py-0.5 rounded text-xs font-mono">$1</code>')
    // 标题
    .replace(/^### (.+)$/gm, '<h4 class="text-sm font-semibold text-gray-800 mt-2 mb-1">$1</h4>')
    .replace(/^## (.+)$/gm, '<h3 class="text-sm font-semibold text-gray-900 mt-3 mb-1">$1</h3>')
    // 无序列表
    .replace(/^[-*] (.+)$/gm, '<li class="ml-3 text-sm">• $1</li>')
    // 换行
    .replace(/\n\n/g, '<br/><br/>')
    .replace(/\n/g, '<br/>')
  return html
}

export default function Workspace() {
  const [input, setInput] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [fullscreenPreview, setFullscreenPreview] = useState(false)
  const [executionStep, setExecutionStep] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const workspaceTaskIdRef = useRef<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)
  const stepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { createTask, currentTask } = useTaskStore(
    (s) => ({ createTask: s.createTask, currentTask: s.currentTask })
  )
  const {
    messages,
    currentOutput,
    previousOutput,
    previewFile,
    showComparison,
    sidebarCollapsed,
    addMessage,
    clearMessages,
    setCurrentOutput,
    setPreviewFile,
    setShowComparison,
    setSidebarCollapsed,
  } = useWorkspaceStore()

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  const getFileUrl = (file: OutputFile) => `/api/downloads/${currentTask?.id}/${encodeURIComponent(file.name)}`
  const getPreviewUrl = (file: OutputFile) => {
    if (isTifFile(file.name) && currentTask?.id) {
      return `/api/downloads/${currentTask.id}/preview/${encodeURIComponent(file.name)}`
    }
    return getFileUrl(file)
  }
  const isGifFile = (name: string) => name.endsWith('.gif')
  const isImageFile = (name: string) => /\.(png|jpg|jpeg|tif|tiff)$/i.test(name)
  const isTifFile = (name: string) => /\.(tif|tiff)$/i.test(name)
  const isHtmlFile = (name: string) => name.endsWith('.html')

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // textarea 自适应高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px'
    }
  }, [input])

  // 组件卸载时取消轮询
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
      if (stepTimerRef.current) clearInterval(stepTimerRef.current)
    }
  }, [])

  // 模拟执行进度（后端暂不暴露中间步骤，用时间估算）
  const startStepSimulation = () => {
    setExecutionStep(0)
    stepTimerRef.current = setInterval(() => {
      setExecutionStep(s => s + 1)
    }, 3000)
  }
  const stopStepSimulation = () => {
    if (stepTimerRef.current) {
      clearInterval(stepTimerRef.current)
      stepTimerRef.current = null
    }
  }

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || isProcessing) return

    const userMessage = input
    setInput('')
    setIsProcessing(true)
    startStepSimulation()

    addMessage({ role: 'user', content: userMessage })

    abortRef.current?.abort()
    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      let task = await createTask({ input_text: userMessage })
      workspaceTaskIdRef.current = task.id

      const maxWait = 300000
      const pollInterval = 2000
      const startTime = Date.now()

      while (task.status !== 'completed' && task.status !== 'failed' && task.status !== 'cancelled') {
        if (Date.now() - startTime > maxWait) {
          addMessage({ role: 'assistant', content: '⏰ 任务执行超时，请稍后在任务列表查看结果。', taskId: task.id })
          setIsProcessing(false)
          stopStepSimulation()
          return
        }
        try {
          await new Promise((resolve, reject) => {
            const t = setTimeout(resolve, pollInterval)
            abortController.signal.addEventListener('abort', () => {
              clearTimeout(t)
              reject(new DOMException('已取消', 'AbortError'))
            })
          })
        } catch {
          if (!mountedRef.current) return
        }
        if (abortController.signal.aborted) return
        task = await tasksService.getTask(task.id)
      }

      if (abortController.signal.aborted || !mountedRef.current) return
      stopStepSimulation()

      useTaskStore.setState({ currentTask: task })

      if (task.status === 'completed') {
        const files = (task.output_files || []) as OutputFile[]
        if (files.length > 0) {
          setCurrentOutput(files)
          const gifFile = files.find((f: OutputFile) => f.name.endsWith('.gif'))
          const mapFile = files.find((f: OutputFile) => f.name.includes('_map.png'))
          const lstFile = files.find((f: OutputFile) => f.name.includes('_lst.png'))
          setPreviewFile(gifFile || mapFile || lstFile || files[0])
        }

        const answer = task.final_answer
        if (answer && answer.trim()) {
          addMessage({ role: 'assistant', content: answer, taskId: task.id })
        } else if (files.length > 0) {
          const fileList = files.map((f: OutputFile) => `- ${f.name} (${formatSize(f.size)})`).join('\n')
          addMessage({ role: 'assistant', content: `**任务完成**\n\n生成文件：\n${fileList}`, taskId: task.id })
        }
        processedTaskIds.add(task.id)
      } else if (task.status === 'failed') {
        addMessage({ role: 'assistant', content: `**任务执行失败**\n\n${task.error_message || '未知错误'}`, taskId: task.id })
        processedTaskIds.add(task.id)
      }
    } catch {
      toast.error('任务提交失败')
      addMessage({ role: 'assistant', content: '**任务提交失败**，请检查后端服务是否正常。' })
    } finally {
      setIsProcessing(false)
      stopStepSimulation()
    }
  }, [input, isProcessing, addMessage, createTask, setCurrentOutput, setPreviewFile])

  const handleClearChat = () => {
    clearMessages()
    setCurrentOutput([])
    setPreviewFile(null)
    processedTaskIds.clear()
    workspaceTaskIdRef.current = null
  }

  const handleFileClick = (file: OutputFile) => {
    if (isImageFile(file.name) || isGifFile(file.name) || isHtmlFile(file.name) || file.name.endsWith('.csv')) {
      setPreviewFile(file)
      // 非图片文件退出对比模式
      if (!isImageFile(file.name)) setShowComparison(false)
    } else {
      window.open(getFileUrl(file), '_blank')
    }
  }

  // 文件分组
  const groupedFiles = {
    images: currentOutput.filter(f => isImageFile(f.name) && !isGifFile(f.name)),
    gifs: currentOutput.filter(f => isGifFile(f.name)),
    html: currentOutput.filter(f => isHtmlFile(f.name)),
    other: currentOutput.filter(f => !isImageFile(f.name) && !isGifFile(f.name) && !isHtmlFile(f.name)),
  }

  const renderFileGroup = (label: string, files: OutputFile[], icon: JSX.Element) => {
    if (files.length === 0) return null
    return (
      <div className="space-y-1">
        <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium pl-1">{label} ({files.length})</p>
        {files.map(f => (
          <button
            key={f.relative_path || f.name}
            onClick={() => handleFileClick(f)}
            className="flex items-center w-full text-left px-2 py-1 rounded hover:bg-white/50 transition-colors group"
          >
            {icon}
            <span className="text-xs truncate flex-1 group-hover:underline">{f.name}</span>
            <span className="text-xs text-gray-400 ml-2 flex-shrink-0">{formatSize(f.size)}</span>
          </button>
        ))}
      </div>
    )
  }

  const renderFileList = (files: OutputFile[]) => {
    const images = files.filter(f => isImageFile(f.name) && !isGifFile(f.name))
    const gifs = files.filter(f => isGifFile(f.name))
    const html = files.filter(f => isHtmlFile(f.name))
    const other = files.filter(f => !isImageFile(f.name) && !isGifFile(f.name) && !isHtmlFile(f.name))

    if (images.length + gifs.length + html.length + other.length <= 3) {
      // 文件少时不分组
      return (
        <div className="mt-2 space-y-1">
          {files.map(f => (
            <button
              key={f.relative_path || f.name}
              onClick={() => handleFileClick(f)}
              className="flex items-center w-full text-left px-2 py-1 rounded hover:bg-white/50 transition-colors group"
            >
              {isGifFile(f.name) ? <Film className="h-3.5 w-3.5 mr-2 text-green-600 flex-shrink-0" />
               : isImageFile(f.name) ? <FileImage className="h-3.5 w-3.5 mr-2 text-blue-600 flex-shrink-0" />
               : isHtmlFile(f.name) ? <FileText className="h-3.5 w-3.5 mr-2 text-purple-600 flex-shrink-0" />
               : <FileText className="h-3.5 w-3.5 mr-2 text-gray-500 flex-shrink-0" />}
              <span className="text-xs truncate flex-1 group-hover:underline">{f.name}</span>
              <span className="text-xs text-gray-400 ml-2 flex-shrink-0">{formatSize(f.size)}</span>
            </button>
          ))}
        </div>
      )
    }

    return (
      <div className="mt-2 space-y-2">
        {renderFileGroup('图片', images, <FileImage className="h-3.5 w-3.5 mr-2 text-blue-600 flex-shrink-0" />)}
        {renderFileGroup('GIF 动画', gifs, <Film className="h-3.5 w-3.5 mr-2 text-green-600 flex-shrink-0" />)}
        {renderFileGroup('网页', html, <FileText className="h-3.5 w-3.5 mr-2 text-purple-600 flex-shrink-0" />)}
        {renderFileGroup('其他', other, <FileText className="h-3.5 w-3.5 mr-2 text-gray-500 flex-shrink-0" />)}
      </div>
    )
  }

  const examples = [
    '下载成都市双流区2024年8月Landsat数据，做温度反演并制图',
    '生成北京市2020-2024年LST时间序列动画',
    '把图例移到左侧，配色改成 viridis',
    '对当前结果做自然断点分类',
  ]

  return (
    <div className="h-[calc(100vh-64px)] flex overflow-hidden bg-gray-50">
      {/* ── 左侧对话面板 ── */}
      <div className={`${sidebarCollapsed ? 'w-12 min-w-[3rem]' : 'w-[400px] min-w-[340px]'} flex-shrink-0 flex flex-col border-r bg-white transition-all duration-300 relative`}>
        <button
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          className="absolute top-4 -right-3 z-10 bg-white border rounded-full p-1 shadow-sm hover:bg-gray-50 transition-colors"
        >
          {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>

        {!sidebarCollapsed && (
          <>
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-gray-800">GIS 智能助手</h3>
                <p className="text-[10px] text-gray-400 flex items-center gap-1">
                  <Cpu className="h-2.5 w-2.5" />AI 驱动 · 遥感分析
                </p>
              </div>
              <button onClick={handleClearChat} className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors" title="清空对话">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[90%] rounded-2xl px-4 py-2.5 ${
                      msg.role === 'user'
                        ? 'bg-primary-600 text-white rounded-br-md'
                        : msg.role === 'system'
                        ? 'bg-blue-50 text-blue-700 border border-blue-200 rounded-bl-md'
                        : 'bg-gray-100 text-gray-800 rounded-bl-md'
                    }`}
                  >
                    {msg.role === 'assistant' ? (
                      <div
                        className="text-sm leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                      />
                    ) : (
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    )}
                    {msg.taskId && currentOutput.length > 0 && msg.role === 'assistant' && (
                      renderFileList(currentOutput)
                    )}
                    <p className={`text-[10px] mt-1.5 ${msg.role === 'user' ? 'text-blue-200' : 'text-gray-400'}`}>
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              {isProcessing && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-2.5 min-w-[200px]">
                    <div className="flex items-center space-x-2">
                      <Loader2 className="h-4 w-4 animate-spin text-primary-600" />
                      <span className="text-sm text-gray-600 font-medium">Agent 执行中</span>
                    </div>
                    {executionStep > 0 && (
                      <div className="mt-2 flex items-center space-x-1.5 text-xs text-gray-500">
                        <div className="flex space-x-1">
                          {[0, 1, 2].map((i) => (
                            <div
                              key={i}
                              className={`h-1.5 w-1.5 rounded-full transition-colors duration-500 ${
                                i <= executionStep % 3 ? 'bg-primary-500' : 'bg-gray-300'
                              }`}
                            />
                          ))}
                        </div>
                        <span>步骤 {executionStep}</span>
                      </div>
                    )}
                    {/* 进度条 */}
                    <div className="mt-2 w-full bg-gray-200 rounded-full h-1 overflow-hidden">
                      <div
                        className="bg-primary-500 h-full rounded-full transition-all duration-1000 ease-out"
                        style={{ width: `${Math.min((executionStep / 15) * 100, 90)}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* 示例提示 */}
            {messages.length <= 1 && (
              <div className="px-4 pb-2">
                <p className="text-xs text-gray-400 mb-2">试试这些示例：</p>
                <div className="flex flex-wrap gap-1.5">
                  {examples.map((ex, i) => (
                    <button
                      key={i}
                      onClick={() => { setInput(ex); textareaRef.current?.focus() }}
                      className="text-xs px-2.5 py-1.5 bg-gray-50 hover:bg-gray-100 text-gray-600 rounded-full border transition-colors truncate max-w-[180px]"
                      title={ex}
                    >
                      {ex.length > 18 ? ex.slice(0, 18) + '...' : ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 输入区域 */}
            <div className="p-3 border-t">
              <div className="flex items-end space-x-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSubmit()
                    }
                  }}
                  placeholder="输入 GIS 需求... (Enter 发送，Shift+Enter 换行)"
                  className="flex-1 px-3 py-2 border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent text-sm resize-none"
                  rows={1}
                  disabled={isProcessing}
                />
                <button
                  onClick={handleSubmit}
                  disabled={isProcessing || !input.trim()}
                  className="px-4 py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                >
                  {isProcessing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── 右侧画布面板 ── */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* 顶部工具栏 */}
        <div className="bg-white border-b px-4 py-2 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <h3 className="font-semibold text-gray-800">画布预览</h3>
            {currentOutput.length > 0 && (
              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{currentOutput.length} 个文件</span>
            )}
            {previewFile && (
              <span className="text-xs text-gray-500 truncate max-w-[200px] hidden sm:inline">{previewFile.name}</span>
            )}
          </div>
          <div className="flex items-center space-x-2">
            {previousOutput.length > 0 && currentOutput.length > 0 && previewFile && isImageFile(previewFile.name) && (
              <button
                onClick={() => setShowComparison(!showComparison)}
                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  showComparison ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {showComparison ? '退出对比' : '对比上次结果'}
              </button>
            )}
            {previewFile && (isImageFile(previewFile.name) || isGifFile(previewFile.name)) && (
              <button
                onClick={() => setFullscreenPreview(!fullscreenPreview)}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
                title={fullscreenPreview ? '退出全屏' : '全屏预览'}
              >
                {fullscreenPreview ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
            )}
          </div>
        </div>

        {/* 预览区域 */}
        <div className={`flex-1 overflow-auto ${fullscreenPreview ? 'p-0 bg-black' : 'p-6'}`}>
          {currentOutput.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-gray-400">
                <ImageIcon className="h-20 w-20 mx-auto mb-4 opacity-30" />
                <p className="text-lg font-medium">等待任务结果</p>
                <p className="text-sm mt-2 max-w-sm">在左侧对话框输入 GIS 需求，结果将在这里预览。支持滚轮缩放。</p>
              </div>
            </div>
          ) : showComparison && previousOutput.length > 0 ? (
            /* 对比视图 — 使用滑块对比 */
            <div className="h-full flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wide">对比模式 · 拖拽中线查看差异</h4>
              </div>
              <div className="flex-1 bg-white rounded-xl shadow-sm border overflow-hidden min-h-0">
                {previewFile && (
                  <CompareSlider
                    srcBefore={getPreviewUrl(previousOutput[0])}
                    srcAfter={getPreviewUrl(previewFile)}
                    labelBefore="上次"
                    labelAfter="本次"
                  />
                )}
              </div>
            </div>
          ) : (
            /* 智能查看器 — 根据文件类型自动切换 */
            <div className="h-full flex flex-col">
              <div className="flex-1 flex items-center justify-center min-h-0">
                {previewFile && (
                  <div className={`${fullscreenPreview ? 'w-full h-full' : 'max-w-5xl w-full'} bg-white rounded-xl shadow-lg overflow-hidden`}>
                    <ViewerRouter
                      file={previewFile}
                      src={getPreviewUrl(previewFile)}
                    />
                  </div>
                )}
              </div>

              {/* 缩略图条 —— 按类型分组 */}
              {currentOutput.length > 1 && !fullscreenPreview && (
                <div className="mt-4 space-y-2">
                  {/* 图片组 */}
                  {groupedFiles.images.length > 0 && (
                    <div>
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium mb-1.5 text-center">图片 ({groupedFiles.images.length})</p>
                      <div className="flex space-x-2 overflow-x-auto pb-1 justify-center">
                        {groupedFiles.images.map((file) => (
                          <button
                            key={file.relative_path || file.name}
                            onClick={() => setPreviewFile(file)}
                            className={`flex-shrink-0 w-16 h-16 rounded-lg border-2 overflow-hidden transition-all ${
                              previewFile?.name === file.name
                                ? 'border-primary-500 ring-2 ring-primary-200 shadow-md'
                                : 'border-gray-200 hover:border-gray-400'
                            }`}
                            title={file.name}
                          >
                            <img loading="lazy" src={getPreviewUrl(file)} alt={file.name} className="w-full h-full object-cover" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* GIF 组 */}
                  {groupedFiles.gifs.length > 0 && (
                    <div>
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium mb-1.5 text-center">GIF 动画 ({groupedFiles.gifs.length})</p>
                      <div className="flex space-x-2 overflow-x-auto pb-1 justify-center">
                        {groupedFiles.gifs.map((file) => (
                          <button
                            key={file.relative_path || file.name}
                            onClick={() => setPreviewFile(file)}
                            className={`flex-shrink-0 w-16 h-16 rounded-lg border-2 overflow-hidden transition-all flex items-center justify-center bg-green-50 ${
                              previewFile?.name === file.name
                                ? 'border-primary-500 ring-2 ring-primary-200 shadow-md'
                                : 'border-gray-200 hover:border-gray-400'
                            }`}
                            title={file.name}
                          >
                            <Film className="h-5 w-5 text-green-500" />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* 其他文件组 */}
                  {(groupedFiles.html.length > 0 || groupedFiles.other.length > 0) && (
                    <div>
                      <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium mb-1.5 text-center">其他文件</p>
                      <div className="flex space-x-2 overflow-x-auto pb-1 justify-center">
                        {[...groupedFiles.html, ...groupedFiles.other].map((file) => (
                          <button
                            key={file.relative_path || file.name}
                            onClick={() => window.open(getFileUrl(file), '_blank')}
                            className="flex-shrink-0 w-16 h-16 rounded-lg border-2 border-gray-200 hover:border-gray-400 overflow-hidden transition-all flex items-center justify-center bg-gray-50"
                            title={file.name}
                          >
                            {isHtmlFile(file.name) ? (
                              <FileText className="h-5 w-5 text-purple-500" />
                            ) : (
                              <BarChart3 className="h-5 w-5 text-gray-400" />
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部状态栏 */}
        {previewFile && !fullscreenPreview && (
          <div className="bg-white border-t px-4 py-2 flex items-center justify-between text-sm">
            <div className="flex items-center space-x-3 min-w-0">
              <span className="text-gray-700 font-medium truncate">{previewFile.name}</span>
              <span className="text-gray-400 text-xs flex-shrink-0">{formatSize(previewFile.size)}</span>
            </div>
            <div className="flex items-center space-x-2 flex-shrink-0">
              <a
                href={getFileUrl(previewFile)}
                download={previewFile.name}
                className="flex items-center text-primary-600 hover:text-primary-700 text-xs font-medium px-3 py-1.5 bg-primary-50 hover:bg-primary-100 rounded-lg transition-colors"
              >
                <Download className="h-3.5 w-3.5 mr-1" />
                下载
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
