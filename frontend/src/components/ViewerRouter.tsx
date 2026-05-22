import { FileWarning, Download } from 'lucide-react'
import ImageViewer from './ImageViewer'
import GifPlayer from './GifPlayer'
import TimeSeriesChart from './TimeSeriesChart'
import HtmlPreview from './HtmlPreview'
import type { OutputFile } from '../types/conversation'

interface ViewerRouterProps {
  file: OutputFile
  src: string
}

export default function ViewerRouter({ file, src }: ViewerRouterProps) {
  const name = file.name.toLowerCase()

  // GIF 动画
  if (name.endsWith('.gif')) {
    return <GifPlayer src={src} filename={file.name} />
  }

  // CSV 时间序列
  if (name.endsWith('.csv')) {
    return <TimeSeriesChart src={src} filename={file.name} />
  }

  // HTML 交互地图/报告
  if (name.endsWith('.html') || name.endsWith('.htm')) {
    return <HtmlPreview src={src} filename={file.name} />
  }

  // TIF/TIFF - 浏览器无法直接预览，显示占位并提供下载
  if (name.endsWith('.tif') || name.endsWith('.tiff')) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-gray-100">
        <div className="text-center text-gray-400 px-4">
          <FileWarning className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium text-gray-500">TIF 栅格文件</p>
          <p className="text-xs mt-1 mb-4 max-w-[250px] truncate" title={file.name}>{file.name}</p>
          <a
            href={src}
            download={file.name}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm text-white bg-blue-500 hover:bg-blue-600 rounded-lg transition-colors"
          >
            <Download className="h-4 w-4" />
            下载文件
          </a>
        </div>
      </div>
    )
  }

  // 图片（默认）— 使用 absolute inset-0 填满 relative 定位的父容器
  return <ImageViewer src={src} alt={file.name} className="absolute inset-0" />
}
