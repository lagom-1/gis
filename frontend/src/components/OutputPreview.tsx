import { useState } from 'react'
import { FileImage, FileText, Download, X, ZoomIn, Play } from 'lucide-react'
import ViewerRouter from './ViewerRouter'

interface OutputFile {
  name: string
  path: string
  relative_path?: string
  size: number
  modified: string
}

interface OutputPreviewProps {
  files: OutputFile[] | Record<string, string>
  taskId?: number
}

export default function OutputPreview({ files, taskId }: OutputPreviewProps) {
  const [previewFile, setPreviewFile] = useState<OutputFile | null>(null)
  const isArray = Array.isArray(files)

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  const getFileIcon = (filename: string) => {
    if (filename.match(/\.(png|jpg|jpeg|gif|tif|tiff)$/i)) {
      return <FileImage className="h-5 w-5 text-blue-500" />
    }
    return <FileText className="h-5 w-5 text-gray-500" />
  }

  const isImageFile = (filename: string) => {
    return filename.match(/\.(png|jpg|jpeg|tif|tiff)$/i)
  }

  const isTifFile = (filename: string) => {
    return filename.match(/\.(tif|tiff)$/i)
  }

  const isGifFile = (filename: string) => {
    return filename.match(/\.gif$/i)
  }

  const getFileUrl = (file: OutputFile) => {
    return `/api/downloads/${taskId}/${encodeURIComponent(file.name)}`
  }

  const getPreviewUrl = (file: OutputFile) => {
    if (isTifFile(file.name) && taskId) {
      return `/api/downloads/${taskId}/preview/${encodeURIComponent(file.name)}`
    }
    return getFileUrl(file)
  }

  const handlePreview = (file: OutputFile) => {
    setPreviewFile(file)
  }

  if (isArray) {
    const fileList = files as OutputFile[]
    if (fileList.length === 0) {
      return <p className="text-gray-500">暂无输出文件</p>
    }

    // 分类文件
    const gifFiles = fileList.filter(f => isGifFile(f.name))
    const imageFiles = fileList.filter(f => isImageFile(f.name))
    const otherFiles = fileList.filter(f => !isImageFile(f.name) && !isGifFile(f.name))

    return (
      <div className="space-y-6">
        <h4 className="font-medium text-gray-700">输出文件 ({fileList.length})</h4>

        {/* GIF 动画 - 优先展示 */}
        {gifFiles.length > 0 && (
          <div className="space-y-3">
            <h5 className="text-sm font-medium text-gray-600 flex items-center">
              <Play className="h-4 w-4 mr-1 text-green-500" />
              时间序列动画
            </h5>
            <div className="grid grid-cols-1 gap-4">
              {gifFiles.map((file) => (
                <div
                  key={file.relative_path || file.name}
                  className="bg-gray-50 rounded-lg overflow-hidden border"
                >
                  <div
                    className="relative group cursor-pointer bg-black"
                    onClick={() => handlePreview(file)}
                  >
                    <img loading="lazy"
                      src={getPreviewUrl(file)}
                      alt={file.name}
                      className="w-full max-h-96 object-contain mx-auto"
                    />
                    <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all flex items-center justify-center">
                      <ZoomIn className="h-12 w-12 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </div>
                  <div className="p-4">
                    <p className="font-medium text-gray-900">{file.name}</p>
                    <p className="text-sm text-gray-500 mt-1">{formatSize(file.size)}</p>
                    <a
                      href={getFileUrl(file)}
                      download={file.name}
                      className="mt-3 inline-flex items-center px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
                    >
                      <Download className="h-4 w-4 mr-2" />
                      下载 GIF 动画
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 图片文件 */}
        {imageFiles.length > 0 && (
          <div className="space-y-3">
            <h5 className="text-sm font-medium text-gray-600 flex items-center">
              <FileImage className="h-4 w-4 mr-1 text-blue-500" />
              图片文件
            </h5>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {imageFiles.map((file) => (
                <div
                  key={file.relative_path || file.name}
                  className="bg-gray-50 rounded-lg overflow-hidden border"
                >
                  <div
                    className="relative group cursor-pointer h-48 bg-gray-100"
                    onClick={() => handlePreview(file)}
                  >
                    <img loading="lazy"
                      src={getPreviewUrl(file)}
                      alt={file.name}
                      className="w-full h-full object-contain"
                    />
                    <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-30 transition-all flex items-center justify-center">
                      <ZoomIn className="h-8 w-8 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </div>
                  <div className="p-3">
                    <p className="text-sm font-medium text-gray-900 truncate">{file.name}</p>
                    <p className="text-xs text-gray-500 mt-1">{formatSize(file.size)}</p>
                    <a
                      href={getFileUrl(file)}
                      download={file.name}
                      className="mt-2 inline-flex items-center text-xs text-primary-600 hover:text-primary-700"
                    >
                      <Download className="h-3 w-3 mr-1" />
                      下载
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 其他文件（CSV/HTML 可预览，其余仅下载） */}
        {otherFiles.length > 0 && (
          <div className="space-y-3">
            <h5 className="text-sm font-medium text-gray-600 flex items-center">
              <FileText className="h-4 w-4 mr-1 text-gray-500" />
              其他文件
            </h5>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {otherFiles.map((file) => {
                const canPreview = file.name.endsWith('.html') || file.name.endsWith('.htm') || file.name.endsWith('.csv')
                return (
                <div
                  key={file.relative_path || file.name}
                  className={`flex items-center justify-between p-3 bg-gray-50 rounded-lg border ${
                    canPreview ? 'cursor-pointer hover:bg-gray-100 transition-colors' : ''
                  }`}
                  onClick={canPreview ? () => handlePreview(file) : undefined}
                >
                  <div className="flex items-center space-x-3 min-w-0">
                    {getFileIcon(file.name)}
                    <div className="min-w-0">
                      <p className={`text-sm truncate ${canPreview ? 'font-medium text-primary-700' : 'font-medium text-gray-900'}`}>{file.name}</p>
                      <p className="text-xs text-gray-500">{formatSize(file.size)}</p>
                    </div>
                  </div>
                  <a
                    href={getFileUrl(file)}
                    download={file.name}
                    className="ml-2 p-2 text-gray-400 hover:text-primary-600"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Download className="h-4 w-4" />
                  </a>
                </div>
              )})}
            </div>
          </div>
        )}

        {/* 预览弹窗 — 使用智能查看器 */}
        {previewFile && (
          <div
            className="fixed inset-0 z-50 bg-black bg-opacity-90 flex items-center justify-center p-4"
            onClick={() => setPreviewFile(null)}
          >
            <button
              className="absolute top-4 right-4 text-white hover:text-gray-300 z-10"
              onClick={() => setPreviewFile(null)}
            >
              <X className="h-8 w-8" />
            </button>
            <div className="w-full max-w-5xl max-h-full bg-white rounded-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="h-[80vh] flex flex-col">
                <div className="flex-1 min-h-0">
                  <ViewerRouter file={previewFile} src={getPreviewUrl(previewFile)} />
                </div>
                <div className="p-3 border-t flex items-center justify-between flex-shrink-0">
                  <span className="text-sm text-gray-700 font-medium truncate">{previewFile.name}</span>
                  <a
                    href={getFileUrl(previewFile)}
                    download={previewFile.name}
                    className="inline-flex items-center px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 text-sm"
                  >
                    <Download className="h-4 w-4 mr-2" />
                    下载
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  // 对象格式（兼容旧版本）
  const fileEntries = Object.entries(files as Record<string, string>)
  if (fileEntries.length === 0) {
    return <p className="text-gray-500">暂无输出文件</p>
  }

  return (
    <div className="space-y-2">
      <h4 className="font-medium text-gray-700">输出文件</h4>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {fileEntries.map(([key, path]) => {
          const filename = path.split('/').pop() || path
          return (
            <div
              key={key}
              className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
            >
              <div className="flex items-center space-x-3 min-w-0">
                {getFileIcon(filename)}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{key}</p>
                  <p className="text-xs text-gray-500 truncate">{filename}</p>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
