import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { OutputFile } from '../types/conversation'

interface UIStore {
  sidebarOpen: boolean
  viewerMode: 'preview' | 'compare' | 'fullscreen'
  activeFile: OutputFile | null
  toggleSidebar: () => void
  setViewerMode: (mode: UIStore['viewerMode']) => void
  setActiveFile: (file: OutputFile | null) => void
}

export const useUIStore = create<UIStore>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      viewerMode: 'preview',
      activeFile: null,
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setViewerMode: (mode) => set({ viewerMode: mode }),
      setActiveFile: (file) => set({ activeFile: file }),
    }),
    { name: 'opengis-ui' }
  )
)
