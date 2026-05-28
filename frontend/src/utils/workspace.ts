import type { OutputFile } from '../types/conversation'

export function renderMarkdown(text: string): string {
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

export function extractFilesFromResult(result: Record<string, unknown> | undefined): OutputFile[] {
  if (!result || !result.success) return []
  const files: OutputFile[] = []
  const keys = ['output_png', 'output_tif', 'output_gif', 'output_html', 'output_csv', 'histogram_png']
  for (const key of keys) {
    const path = result[key]
    if (typeof path === 'string' && path) {
      const name = path.replace(/\\/g, '/').split('/').pop() || path
      if (name) files.push({ name, path, size: 0, modified: new Date().toISOString() })
    }
  }
  // 兼容旧格式：output_path + format=html
  if (!result.output_html && typeof result.output_path === 'string' && result.format === 'html') {
    const path = result.output_path
    const name = path.replace(/\\/g, '/').split('/').pop() || path
    if (name) files.push({ name, path, size: 0, modified: new Date().toISOString() })
  }
  const of = result.output_files
  if (Array.isArray(of)) {
    for (const f of of) {
      if (f && typeof f === 'object' && f.name) {
        files.push({
          name: String(f.name),
          path: String(f.path || f.name),
          size: Number(f.size || 0),
          modified: String(f.modified || new Date().toISOString()),
        })
      }
    }
  }
  return files
}

export function formatTime(iso: string) {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString()
}

export const isGifFile = (name: string) => name.endsWith('.gif')
export const isImageFile = (name: string) => /\.(png|jpg|jpeg|tif|tiff)$/i.test(name)
export const isTifFile = (name: string) => /\.(tif|tiff)$/i.test(name)
export const isHtmlFile = (name: string) => name.endsWith('.html')
