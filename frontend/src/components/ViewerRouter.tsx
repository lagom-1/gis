import ImageViewer from './ImageViewer'
import GifPlayer from './GifPlayer'
import TimeSeriesChart from './TimeSeriesChart'
import HtmlPreview from './HtmlPreview'
import type { OutputFile } from '../stores/workspaceStore'

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

  // 图片（默认）
  return <ImageViewer src={src} alt={file.name} className="h-full" />
}
