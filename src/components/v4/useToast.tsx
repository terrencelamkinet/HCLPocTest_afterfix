import { useState, useCallback, createContext, useContext, type ReactNode } from 'react'

/* useToast — lightweight toast notification system used for
   click feedback across Topbar/Dashboard buttons. */

interface Toast { id: number; message: string }
const ToastContext = createContext<{ showToast: (msg: string) => void } | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const showToast = useCallback((message: string) => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev, { id, message }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 2600)
  }, [])
  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="dv2-toast-stack">
        {toasts.map(t => <div key={t.id} className="dv2-toast">{t.message}</div>)}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) return { showToast: (msg: string) => console.log('[toast]', msg) }
  return ctx
}
