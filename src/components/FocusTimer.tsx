import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../lib/api'

interface Task { id: string; title: string; priority: string; status: string }

const WORK_MIN = 25
const BREAK_MIN = 5

export default function FocusTimer() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'work' | 'break'>('work')
  const [status, setStatus] = useState<'idle' | 'running' | 'paused'>('idle')
  const [elapsed, setElapsed] = useState(0)        // seconds elapsed in current session
  const [total, setTotal] = useState(WORK_MIN * 60) // total seconds for this mode
  const [sessionsCompleted, setSessionsCompleted] = useState(0)
  const [currentTask, setCurrentTask] = useState<string | null>(null)
  const [notif, setNotif] = useState<string | null>(null)
  const intervalRef = useRef<number | null>(null)

  // Load sessions from localStorage
  useEffect(() => {
    const saved = localStorage.getItem('focus_sessions')
    if (saved) setSessionsCompleted(parseInt(saved, 10) || 0)
  }, [])

  // Fetch highest priority pending task
  useEffect(() => {
    apiClient.get<{ items: Task[]; total: number }>('/api/v1/crm/tasks?limit=20')
      .then(res => {
        const tasks = res.items || []
        const sorted = tasks
          .filter(t => t.status === 'pending' || t.status === 'in_progress')
          .sort((a, b) => {
            const pri = { high: 0, medium: 1, low: 2 }
            return (pri[a.priority as keyof typeof pri] ?? 1) - (pri[b.priority as keyof typeof pri] ?? 1)
          })
        if (sorted.length > 0) setCurrentTask(sorted[0].title)
      })
      .catch(() => {})
  }, [])

  // Timer logic
  const tick = useCallback(() => {
    setElapsed(prev => {
      const next = prev + 1
      if (next >= WORK_MIN * 60 && mode === 'work' && status === 'running') {
        // Work session complete → auto-switch to break
        clearInterval(intervalRef.current!)
        intervalRef.current = null
        setStatus('idle')
        setMode('break')
        setElapsed(0)
        setTotal(BREAK_MIN * 60)
        setSessionsCompleted(s => {
          const n = s + 1
          localStorage.setItem('focus_sessions', String(n))
          return n
        })
        setNotif(t('pages.tasks.focusComplete'))
        setTimeout(() => setNotif(null), 4000)
        return 0
      }
      if (next >= BREAK_MIN * 60 && mode === 'break' && status === 'running') {
        // Break complete → back to work
        clearInterval(intervalRef.current!)
        intervalRef.current = null
        setStatus('idle')
        setMode('work')
        setElapsed(0)
        setTotal(WORK_MIN * 60)
        setNotif(t('pages.tasks.breakOver'))
        setTimeout(() => setNotif(null), 4000)
        return 0
      }
      return next
    })
  }, [mode, status])

  const startTimer = useCallback(() => {
    if (intervalRef.current) return
    setStatus('running')
    setElapsed(prev => prev) // preserve elapsed
    setTotal(mode === 'work' ? WORK_MIN * 60 : BREAK_MIN * 60)
    intervalRef.current = window.setInterval(tick, 1000)
  }, [mode, tick])

  const pauseTimer = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setStatus('paused')
  }, [])

  const resetTimer = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    setStatus('idle')
    setElapsed(0)
    setTotal(mode === 'work' ? WORK_MIN * 60 : BREAK_MIN * 60)
  }, [mode])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  // Progress percentage
  const pct = total > 0 ? (elapsed / total) * 100 : 0
  const remaining = total - elapsed
  const mins = Math.floor(remaining / 60)
  const secs = remaining % 60
  const displayTime = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`

  // SVG circle — circumference = 2 * PI * radius (r=38)
  const r = 38
  const circ = 2 * Math.PI * r
  const offset = circ - (pct / 100) * circ

  return (
    <div className="focus-card">
      {/* Notification banner */}
      {notif && <div className="focus-notif">{notif}</div>}

      {/* Task name */}
      <div className="task-name">{currentTask || t('pages.tasks.focusSession')}</div>
      <div className="task-sub">{mode === 'work' ? t('pages.tasks.focusTime') : t('pages.tasks.breakTime')}</div>

      {/* Circular progress */}
      <div className="focus-ring-svg">
        <svg width="90" height="90" viewBox="0 0 90 90">
          {/* Background ring */}
          <circle cx="45" cy="45" r={r} fill="none" stroke="var(--color-surface-offset-2)" strokeWidth="5" />
          {/* Progress ring */}
          <circle
            cx="45" cy="45" r={r}
            fill="none"
            stroke={mode === 'work' ? 'var(--color-primary)' : 'var(--color-success)'}
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            transform="rotate(-90, 45, 45)"
            style={{ transition: 'stroke-dashoffset 0.5s linear' }}
          />
        </svg>
        <button
          className={`play-btn ${status === 'running' ? 'is-pause' : ''}`}
          onClick={status === 'running' ? pauseTimer : startTimer}
          aria-label={status === 'running' ? t('pages.tasks.paused') : t('pages.tasks.ready')}
        >
          {status === 'running' ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
      </div>

      {/* Timer + meta */}
      <div className="focus-meta">
        <div>
          <div className="v tabular">{displayTime}</div>
          <div className="l">{status === 'idle' ? t('pages.tasks.ready') : status === 'paused' ? t('pages.tasks.paused') : t('pages.tasks.remaining')}</div>
        </div>
        <div>
          <button className="focus-reset" onClick={resetTimer} aria-label={t('pages.tasks.reset')}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 4v6h6M23 20v-6h-6" />
              <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
            </svg>
          </button>
          <div className="l">{t('pages.tasks.reset')}</div>
        </div>
        <div>
          <div className="v">{sessionsCompleted}</div>
          <div className="l">{t('pages.tasks.sessions')}</div>
        </div>
      </div>

      {/* Mode toggle */}
      <div className="focus-mode-toggle">
        <button
          className={`focus-mode-btn ${mode === 'work' ? 'active' : ''}`}
          onClick={() => { resetTimer(); setMode('work'); setTotal(WORK_MIN * 60) }}
        >
          {t('pages.tasks.focusSession')} {WORK_MIN}m
        </button>
        <button
          className={`focus-mode-btn ${mode === 'break' ? 'active' : ''}`}
          onClick={() => { resetTimer(); setMode('break'); setTotal(BREAK_MIN * 60) }}
        >
          {t('pages.tasks.breakTime')} {BREAK_MIN}m
        </button>
      </div>
    </div>
  )
}
