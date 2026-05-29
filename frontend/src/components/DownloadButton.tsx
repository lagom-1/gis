import { useState } from 'react'
import { Download } from 'lucide-react'
import PaymentModal from './PaymentModal'

interface DownloadButtonProps {
  taskId: number
  filename?: string
  className?: string
}

export default function DownloadButton({ taskId, filename, className }: DownloadButtonProps) {
  const [showModal, setShowModal] = useState(false)

  const handleDownload = () => {
    if (filename) {
      const token = localStorage.getItem('token')
      const url = `/api/downloads/serve/${taskId}/${encodeURIComponent(filename)}?token=${token}`
      window.open(url, '_blank')
    }
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className={className || 'px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center gap-2'}
      >
        <Download className="w-4 h-4" />
        下载
      </button>

      <PaymentModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        taskId={taskId}
        onDownload={handleDownload}
      />
    </>
  )
}
