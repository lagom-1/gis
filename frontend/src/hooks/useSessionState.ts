import { useState, useLayoutEffect, useCallback, useRef } from 'react'

function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const stored = sessionStorage.getItem(key)
    return stored ? JSON.parse(stored) : fallback
  } catch {
    return fallback
  }
}

/**
 * 带 sessionStorage 持久化的 useState。
 * 页面切换（路由卸载/重新挂载）时状态不丢失。
 * key 变化时自动重置为新 key 对应的持久化值。
 */
export function useSessionState<T>(key: string, initialValue: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => loadFromStorage(key, initialValue))

  // key 变化时重置状态，避免跨会话数据泄露
  const prevKeyRef = useRef(key)
  const initialRef = useRef(initialValue)
  initialRef.current = initialValue

  useLayoutEffect(() => {
    if (prevKeyRef.current !== key) {
      prevKeyRef.current = key
      setState(loadFromStorage(key, initialRef.current))
    }
  }, [key])

  const setAndPersist = useCallback((value: T | ((prev: T) => T)) => {
    setState(prev => {
      const next = typeof value === 'function' ? (value as (prev: T) => T)(prev) : value
      try { sessionStorage.setItem(key, JSON.stringify(next)) } catch {}
      return next
    })
  }, [key])

  return [state, setAndPersist]
}
