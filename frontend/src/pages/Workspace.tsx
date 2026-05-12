import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Image as ImageIcon, Film, BarChart3, ChevronLeft, ChevronRight, Trash2, FileImage, FileText, Download } from 'lucide-react'
import { useTaskStore } from '../stores/taskStore'
import { useWorkspaceStore, type OutputFile } from '../stores/workspaceStore'
import toast from 'react-hot-toast'

export default function Workspace() {
  const [input, setInput] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [processedTaskId, setProcessedTaskId] = useState<number | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { createTask, currentTask, fetchTask } = useTaskStore()
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

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 轮询任务状态
  useEffect(() => {
    if (!currentTask || currentTask.status === 'completed' || currentTask.status === 'failed') {
      return
    }

    const interval = setInterval(async () => {
      await fetchTask(currentTask.id)
    }, 3000)

    return () => clearInterval(interval)
  }, [currentTask, fetchTask])

  // 任务完成时更新输出 + 显示 Agent 回复
  useEffect(() => {
    if (!currentTask || currentTask.id === processedTaskId) return

    if (currentTask.status === 'completed') {
      const files = (currentTask.output_files || []) as OutputFile[]

      if (files.length > 0) {
        setCurrentOutput(files)
        const gifFile = files.find(f => f.name.endsWith('.gif'))
        const mapFile = files.find(f => f.name.includes('_map.png'))
        const lstFile = files.find(f => f.name.includes('_lst.png'))
        setPreviewFile(gifFile || mapFile || lstFile || files[0])
      }

      const answer = currentTask.final_answer
      if (answer && answer.trim()) {
        addMessage({
          role: 'assistant',
          content: answer,
          taskId: currentTask.id,
        })
      } else {
        const fileList = files.length > 0
          ? `\n\n生成文件：\n${files.map(f => `  ${f.name} (${formatSize(f.size)})`).join('\n')}`
          : ''
        addMessage({
          role: 'assistant',
          content: `任务完成。${fileList}`,
          taskId: currentTask.id,
        })
      }

      setIsProcessing(false)
      setProcessedTaskId(currentTask.id)
    } else if (currentTask.status === 'failed') {
      addMessage({
        role: 'assistant',
        content: `任务失败：${currentTask.error_message || '未知错误'}`,
      })
      setIsProcessing(false)
      setProcessedTaskId(currentTask.id)
    }
  }, [currentTask?.status, currentTask?.id])

  const handleSubmit = async () => {
    if (!input.trim() || isProcessing) return

    const userMessage = input
    setInput('')
    setIsProcessing(true)
    setProcessedTaskId(null)

    addMessage({ role: 'user', content: userMessage })

    try {
      const task = await createTask({ input_text: userMessage })

      if (task.status === 'completed' || task.status === 'failed') {
        await fetchTask(task.id)
      } else {
        addMessage({ role: 'assistant', content: '正在处理中，请稍候...' })
      }
    } catch {
      toast.error('任务提交失败')
      addMessage({ role: 'assistant', content: '任务提交失败，请重试。' })
      setIsProcessing(false)
    }
  }

  const handleClearChat = () => {
    clearMessages()
    setCurrentOutput([])
    setPreviewFile(null)
    setProcessedTaskId(null)
  }

  const getFileUrl = (file: OutputFile) => `/outputs/${file.relative_path || file.name}`
  const isGifFile = (name: string) => name.endsWith('.gif')
  const isImageFile = (name: string) => /\.(png|jpg|jpeg)$/i.test(name)
  const isHtmlFile = (name: string) => name.endsWith('.html')

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  const handleFileClick = (file: OutputFile) => {
    if (isImageFile(file.name) || isGifFile(file.name)) {
      setPreviewFile(file)
    } else {
      window.open(getFileUrl(file), '_blank')
    }
  }

  const renderFileList = (files: OutputFile[]) => (
    <div className="mt-2 space-y-1">
      {files.map(f => (
        <button
          key={f.name}
          onClick={() => handleFileClick(f)}
          className="flex items-center w-full text-left px-2 py-1 rounded hover:bg-white/50 transition-colors group"
        >
          {isGifFile(f.name) ? (
            <Film className="h-3.5 w-3.5 mr-2 text-green-600 flex-shrink-0" />
          ) : isImageFile(f.name) ? (
            <FileImage className="h-3.5 w-3.5 mr-2 text-blue-600 flex-shrink-0" />
          ) : isHtmlFile(f.name) ? (
            <FileText className="h-3.5 w-3.5 mr-2 text-purple-600 flex-shrink-0" />
          ) : (
            <FileText className="h-3.5 w-3.5 mr-2 text-gray-500 flex-shrink-0" />
          )}
          <span className="text-xs truncate flex-1 group-hover:underline">{f.name}</span>
          <span className="text-xs text-gray-400 ml-2 flex-shrink-0">{formatSize(f.size)}</span>
        </button>
      ))}
    </div>
  )

  return (
    <div className="h-[calc(100vh-64px)] flex overflow-hidden">
      {/* 中间对话面板 */}
      <div className={`${sidebarCollapsed ? 'w-12 min-w-[3rem]' : 'w-[380px] min-w-[320px]'} flex-shrink-0 flex flex-col border-r bg-white transition-all duration-300 relative`}>
        <button
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          className="absolute top-4 -right-3 z-10 bg-white border rounded-full p-1 shadow-sm hover:bg-gray-50"
        >
          {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>

        {!sidebarCollapsed && (
          <>
            <div className="px-4 py-3 border-b flex items-center justify-between">
              <h3 className="font-medium text-gray-700">GIS 对话</h3>
              <button onClick={handleClearChat} className="p-1 text-gray-400 hover:text-gray-600" title="清空对话">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[90%] rounded-lg p-3 ${
                      msg.role === 'user'
                        ? 'bg-primary-600 text-white'
                        : msg.role === 'system'
                        ? 'bg-blue-50 text-blue-700 border border-blue-200'
                        : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    {msg.taskId && currentOutput.length > 0 && msg.role === 'assistant' && (
                      renderFileList(currentOutput)
                    )}
                    <p className={`text-xs mt-1 ${msg.role === 'user' ? 'text-blue-200' : 'text-gray-400'}`}>
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              {isProcessing && (
                <div className="flex justify-start">
                  <div className="bg-gray-100 rounded-lg p-3 flex items-center space-x-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span className="text-sm text-gray-600">Agent 正在执行中...</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-4 border-t">
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSubmit()}
                  placeholder="输入 GIS 需求，如：下载成都市2024年Landsat数据做温度反演"
                  className="flex-1 px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm"
                  disabled={isProcessing}
                />
                <button
                  onClick={handleSubmit}
                  disabled={isProcessing || !input.trim()}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isProcessing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* 右侧画布面板 */}
      <div className="flex-1 min-w-0 flex flex-col bg-gray-50">
        <div className="bg-white border-b px-4 py-2 flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <h3 className="font-medium text-gray-700">画布预览</h3>
            {previewFile && (
              <span className="text-sm text-gray-500">{previewFile.name}</span>
            )}
          </div>
          <div className="flex items-center space-x-2">
            {previousOutput.length > 0 && currentOutput.length > 0 && (
              <button
                onClick={() => setShowComparison(!showComparison)}
                className={`px-3 py-1 text-sm rounded-lg ${
                  showComparison ? 'bg-primary-100 text-primary-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {showComparison ? '退出对比' : '对比上次结果'}
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-auto p-6">
          {currentOutput.length === 0 ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-gray-400">
                <ImageIcon className="h-16 w-16 mx-auto mb-4" />
                <p className="text-lg">等待任务结果</p>
                <p className="text-sm mt-2">在左侧对话框输入 GIS 需求，结果将在这里预览</p>
              </div>
            </div>
          ) : showComparison && previousOutput.length > 0 ? (
            <div className="grid grid-cols-2 gap-6 h-full">
              <div className="space-y-2">
                <h4 className="text-sm font-medium text-gray-500">上次结果</h4>
                <div className="bg-white rounded-lg shadow-sm border overflow-hidden h-full flex items-center justify-center">
                  <img src={getFileUrl(previousOutput[0])} alt="上次结果" className="max-w-full max-h-[70vh] object-contain" />
                </div>
              </div>
              <div className="space-y-2">
                <h4 className="text-sm font-medium text-gray-500">本次结果</h4>
                <div className="bg-white rounded-lg shadow-sm border overflow-hidden h-full flex items-center justify-center">
                  {previewFile && (
                    <img src={getFileUrl(previewFile)} alt="本次结果" className="max-w-full max-h-[70vh] object-contain" />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col">
              <div className="flex-1 flex items-center justify-center">
                {previewFile && (
                  <div className="bg-white rounded-lg shadow-lg overflow-hidden max-w-5xl">
                    <img
                      src={getFileUrl(previewFile)}
                      alt={previewFile.name}
                      className="w-full h-auto max-h-[70vh] object-contain"
                    />
                  </div>
                )}
              </div>

              {currentOutput.length > 1 && (
                <div className="mt-4 flex space-x-3 overflow-x-auto pb-2 justify-center">
                  {currentOutput.map((file) => (
                    <button
                      key={file.name}
                      onClick={() => setPreviewFile(file)}
                      className={`flex-shrink-0 w-20 h-20 rounded-lg border-2 overflow-hidden transition-all ${
                        previewFile?.name === file.name
                          ? 'border-primary-500 ring-2 ring-primary-200'
                          : 'border-gray-200 hover:border-gray-400'
                      }`}
                      title={file.name}
                    >
                      {isGifFile(file.name) ? (
                        <div className="w-full h-full bg-green-50 flex items-center justify-center">
                          <Film className="h-6 w-6 text-green-500" />
                        </div>
                      ) : isImageFile(file.name) ? (
                        <img src={getFileUrl(file)} alt={file.name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full bg-gray-50 flex items-center justify-center">
                          <BarChart3 className="h-6 w-6 text-gray-400" />
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {previewFile && (
          <div className="bg-white border-t px-4 py-2 flex items-center justify-between text-sm">
            <div className="flex items-center space-x-4">
              <span className="text-gray-600 font-medium">{previewFile.name}</span>
              <span className="text-gray-400">{formatSize(previewFile.size)}</span>
            </div>
            <a
              href={getFileUrl(previewFile)}
              download={previewFile.name}
              className="flex items-center text-primary-600 hover:text-primary-700"
            >
              <Download className="h-4 w-4 mr-1" />
              下载
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
