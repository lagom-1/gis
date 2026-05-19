import { useState, useEffect, useCallback } from 'react'

/**
 * 带 sessionStorage 持久化的 useState。
 * 页面切换（路由卸载/重新挂载）时状态不丢失。
 */
export function useSessionState<T>(key: string, initialValue: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    try {
      const stored = sessionStorage.getItem(key)
      return stored ? JSON.parse(stored) : initialValue
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(state))
    } catch { /* quota exceeded, ignore */ }
  }, [key, state])

  const setAndPersist = useCallback((value: T | ((prev: T) => T)) => {
    setState(prev => {
      const next = typeof value === 'function' ? (value as (prev: T) => T)(prev) : value
      try { sessionStorage.setItem(key, JSON.stringify(next)) } catch {}
      return next
    })
  }, [key])

  return [state, setAndPersist]
}
