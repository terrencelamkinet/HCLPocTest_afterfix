import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import SvcIcon from '../components/SvcIcon'
import { CreditCard, Monitor, Puzzle, Users } from 'lucide-react'
import { apiClient, uploadFile } from '../lib/api'
import { useAuth } from '../lib/AuthContext'
import LanguageSwitcher from '../i18n/LanguageSwitcher';
// 2026-09-10 Terrence: subscription / 用量由 AI panel 搬嚟呢度（個人資料）
import { useQuota } from '../components/ai/chat/core/AICoreHooks';

// 頭像／時區（2026-09-11）：時區清單刻意保持短——夠常用就算；如果 DB 存住
// 一個唔在清單嘅時區，前端會動態補上，唔會靜靜改走用戶設定。
const TIMEZONES = [
  'Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Taipei', 'Asia/Singapore',
  'Asia/Tokyo', 'Asia/Seoul', 'Australia/Sydney', 'Europe/London',
  'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'UTC',
]

const tabs = [
  { id: 'profile', label: 'Profile', icon: Users },
  { id: 'team', label: 'Team', icon: Users },
  { id: 'modules', label: 'Modules', icon: Puzzle },
  { id: 'billing', label: 'Billing', icon: CreditCard },
  { id: 'preferences', label: 'Preferences', icon: Monitor },
]

export default function SettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate()
  const { user, refreshMe } = useAuth()
  const quota = useQuota()
  const [active, setActive] = useState('profile')
  // ── Profile（個人資料）──
  const [name, setName] = useState('')
  const [tz, setTz] = useState('')
  const [avatarFailed, setAvatarFailed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [profileSave, setProfileSave] = useState<'idle' | 'saving' | 'done'>('idle')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setName(user?.displayName || '')
    setTz(user?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Hong_Kong')
  }, [user?.displayName, user?.timezone])

  // 換咗頭像 URL 就重試一次圖片；上一次 load 失敗唔應該永遠卡住
  useEffect(() => { setAvatarFailed(false) }, [user?.avatarUrl])

  const initials = (user?.displayName || user?.email || '?')
    .split(' ').map((s: string) => s[0]).slice(0, 2).join('').toUpperCase()

  const tzList = TIMEZONES.includes(tz) ? TIMEZONES : [...TIMEZONES, tz].filter(Boolean)

  const onPickAvatar = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0]
    e.target.value = ''
    if (!picked) return
    setUploading(true)
    try {
      await uploadFile('/api/v1/auth/me/avatar', picked)
      await refreshMe()
    } catch (err: any) {
      alert(err?.detail || err?.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const saveProfile = async () => {
    setProfileSave('saving')
    try {
      await apiClient.patch('/api/v1/auth/me', { display_name: name.trim(), timezone: tz })
      await refreshMe()
      setProfileSave('done')
      setTimeout(() => setProfileSave('idle'), 2000)
    } catch {
      setProfileSave('idle')
    }
  }
  const [modules, setModules] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState<Record<string, boolean>>({})
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'done'>('idle')

  // ── Notification preferences ──
  const notifDefs = [
    { key: 'task', icon: '📋', label: 'Task', desc: '被指派任務、今日到期、任務完成通知' },
    { key: 'project', icon: '📁', label: 'Project', desc: '被指派項目、項目 deadline 提醒' },
    { key: 'calendar', icon: '📅', label: 'Calendar', desc: '日程改期、30 分鐘前提醒' },
    { key: 'ai', icon: '🤖', label: 'AI', desc: 'AI 執行完成、AI 洞察通知' },
    { key: 'system', icon: '⚙️', label: 'System', desc: '系統層面通知' },
  ]
  const [notifMuted, setNotifMuted] = useState<Record<string, boolean>>({})
  const [notifDraft, setNotifDraft] = useState<Record<string, boolean>>({})
  const [notifLoading, setNotifLoading] = useState(true)
  const [notifSaveState, setNotifSaveState] = useState<'idle' | 'saving' | 'done'>('idle')

  const loadNotifPrefs = async () => {
    try {
      const list = await apiClient.get('/api/v1/notification-preferences')
      const muted: Record<string, boolean> = {}
      ;(list || []).forEach((p: any) => { muted[p.module_key] = !!p.is_muted })
      setNotifMuted(muted)
      setNotifDraft({})
    } catch {}
    finally { setNotifLoading(false) }
  }

  const saveNotifPrefs = async () => {
    setNotifSaveState('saving')
    try {
      const changed = Object.keys(notifDraft)
        .filter(key => !!notifDraft[key] !== !!notifMuted[key])
        .map(key => ({ module_key: key, is_muted: !!notifDraft[key] }))
      if (changed.length > 0) {
        await apiClient.put('/api/v1/notification-preferences', changed)
      }
      setNotifMuted(p => ({ ...p, ...notifDraft }))
      setNotifDraft({})
      setNotifSaveState('done')
      setTimeout(() => setNotifSaveState('idle'), 2000)
    } catch {
      setNotifSaveState('idle')
    }
  }

  const moduleDefs = [
    { key: 'projects', label: 'Projects', icon: '📊', desc: 'Project-based tracking, budgets, milestones. Links to contacts and companies.' },
    { key: 'shipping', label: 'Shipping', icon: '🚢', desc: 'Shipment tracking, dispatch orders, delivery management.' },
    { key: 'ai_assistant', label: 'AI Assistant', icon: '🤖', desc: 'AI daily briefing, smart widget suggestions, and chat assistant on dashboard.' },
    { key: 'notes', label: 'Notes', icon: '📝', desc: 'Notebooks and private notes. Link a note to contacts, companies, projects or tasks.' },
    // NOTE: 'sales' (Deals) is intentionally omitted from Settings so it can't be
    // re-enabled from the UI — temporarily hidden (see backend HIDDEN_MODULES).
    // To re-open later, re-add the entry below and remove 'sales' from the
    // backend HIDDEN_MODULES set.
    // { key: 'sales', label: 'Sales', icon: '💰', desc: 'Deal pipeline, stages, sales reports, quotes. Links from Contacts.' },
  ]

  const loadModules = async () => {
    try {
      const list = await apiClient.get('/api/v1/crm/module-settings')
      const map: Record<string, boolean> = {}
      ;(list || []).forEach((m: any) => { map[m.module_key] = m.enabled })
      setModules(map)
      setDraft({ ...map })
    } catch {}
    finally { setLoading(false) }
  }

  useEffect(() => { loadModules() }, [])
  useEffect(() => { loadNotifPrefs() }, [])

  const toggleDraft = (key: string) => {
    setDraft(p => ({ ...p, [key]: !p[key] }))
  }

  const saveModules = async () => {
    setSaveState('saving')
    try {
      for (const key of Object.keys(draft)) {
        if (modules[key] !== draft[key]) {
          await apiClient.put(`/api/v1/crm/module-settings/${key}`, { module_key: key, enabled: draft[key] })
        }
      }
      setModules({ ...draft })
      window.dispatchEvent(new CustomEvent('modules-changed'))
      setSaveState('done')
      setTimeout(() => setSaveState('idle'), 2000)
    } catch (e: any) {
      alert(e.detail || e.message)
      setSaveState('idle')
    }
  }

  const cancelChanges = () => setDraft({ ...modules })

  return (
    <div className="stg-page">
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">{t('settings.title')}</span>
      </div>
      <div className="page-header">
        <h1>{t('settings.title')}</h1>
      </div>

      <div className="stg-layout">
        <div className="stg-tabs">
          {tabs.map(tab => (
            <button key={tab.id}
              className={`stg-tab${active === tab.id ? ' active' : ''}`}
              onClick={() => setActive(tab.id)}>
              <tab.icon className="w-4 h-4" />
              {t('settings.tabs.' + tab.id)}
            </button>
          ))}
        </div>

        <div className="stg-content">
          {active === 'profile' && (
            <div className="stg-panel">
              <h2>{t('settings.tabs.profile')}</h2>
              <div className="stg-avatar-section">
                <div className="avatar-lg">
                  {user?.avatarUrl && !avatarFailed
                    ? <img src={user.avatarUrl} alt="" onError={() => setAvatarFailed(true)} />
                    : initials}
                </div>
                <div className="stg-avatar-actions">
                  <button className="btn-ghost" onClick={() => fileRef.current?.click()} disabled={uploading}>
                    {uploading ? t('settings.profile.uploading') : t('settings.profile.changeAvatar')}
                  </button>
                  <span className="stg-avatar-hint">{t('settings.profile.avatarHint')}</span>
                </div>
                <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                  style={{ display: 'none' }} onChange={onPickAvatar} />
              </div>
              <div className="stg-fields">
                <div className="stg-field-row">
                  <label>{t('settings.profile.name')}</label>
                  <input type="text" value={name} maxLength={255} className="input-field"
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('settings.profile.namePlaceholder', { defaultValue: '未設定名稱' })} />
                </div>
                <div className="stg-field-row">
                  <label>{t('settings.profile.email')}</label>
                  <input type="email" value={user?.email || ''} readOnly className="input-field" />
                </div>
                <div className="stg-field-row">
                  <label>{t('settings.profile.timezone')}</label>
                  <select className="input-field" value={tz} onChange={(e) => setTz(e.target.value)}>
                    {tzList.map((zone) => <option key={zone} value={zone}>{zone}</option>)}
                  </select>
                </div>
                <div className="stg-field-row">
                  <label>{t('settings.profile.language')}</label>
                  <LanguageSwitcher />
                </div>
              </div>
              {/* Subscription / 用量（2026-09-10 Terrence: 由 AI panel 搬過嚟） */}
              {quota && (
                <div className="stg-subscription">
                  <h3>{t('settings.profile.subscription', { defaultValue: '訂閱方案' })}</h3>
                  <div className="stg-field-row">
                    <label>{t('settings.profile.plan', { defaultValue: '目前方案' })}</label>
                    <div className="nxc-quota">
                      <div className="nxc-quota-row">
                        <span className={`nxc-sub-badge ${quota.plan === 'pro subscription' ? 'pro' : 'free'}`}>
                          {quota.plan === 'pro subscription' ? 'Pro Subscription' : (quota.plan === 'free subscription' ? 'Free Subscription' : (quota.limit > 0 ? 'Free Subscription' : ''))}
                        </span>
                        {quota.plan === 'pro subscription' && <span className="nxc-pro-unlimited">無限用量</span>}
                        {quota.plan !== 'pro subscription' && quota.limit > 0 && (
                          <>
                            <span>{quota.periodLabel} AI 使用量</span>
                            <span className={`nxc-quota-value ${(quota.used / quota.limit) >= 0.8 ? 'warn' : ''}`}>
                              {quota.used.toLocaleString()} / {quota.limit.toLocaleString()}
                            </span>
                          </>
                        )}
                      </div>
                      {quota.plan !== 'pro subscription' && quota.limit > 0 && (
                        <div className="nxc-quota-track">
                          <div className={`nxc-quota-fill ${(quota.used / quota.limit) >= 0.8 ? 'warn' : ''}`}
                            style={{ width: `${Math.min(100, Math.round((quota.used / quota.limit) * 100))}%` }} />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <button className={`btn-primary${profileSave === 'saving' ? ' btn-saving' : ''}${profileSave === 'done' ? ' btn-done' : ''}`}
                onClick={saveProfile} disabled={profileSave !== 'idle'}>
                {profileSave === 'idle' && t('settings.profile.save')}
                {profileSave === 'saving' && <span className="btn-spinner" />}
                {profileSave === 'done' && <span className="btn-check">✓</span>}
              </button>
            </div>
          )}

          {active === 'team' && (
            <div className="stg-panel">
              <h2>{t('settings.tabs.team')}</h2>
              <div className="stg-team-list">
                {[
                  { name: user?.displayName || user?.email?.split('@')[0] || 'You', email: user?.email || '', role: 'Admin' },
                ].map((m, i) => (
                  <div key={i} className="stg-team-row">
                    <div className="stg-team-avatar">{m.name.split(' ').map(n => n[0]).join('')}</div>
                    <div className="stg-team-info">
                      <p className="stg-team-name">{m.name}</p>
                      <p className="stg-team-email">{m.email}</p>
                    </div>
                    <span className="stg-role-badge">{m.role}</span>
                  </div>
                ))}
              </div>
              <button className="btn-secondary"><SvcIcon name="users" className="w-4 h-4" /> Invite Member</button>
            </div>
          )}

          {active === 'modules' && (
            <div className="stg-panel">
              <h2>{t('settings.tabs.modules')}</h2>
              <p className="stg-subtitle">Enable or disable CRM modules. Disabling a module hides its navigation and pages.</p>
              {loading ? (
                <div className="stg-loading">{t('settings.loading')}</div>
              ) : (
                <div className="stg-module-list">
                  {moduleDefs.map(def => (
                    <div key={def.key} className="stg-module-row"
                      onClick={() => toggleDraft(def.key)}>
                      <div className="stg-module-icon">{def.icon}</div>
                      <div className="stg-module-info">
                        <p className="stg-module-name">{def.label}</p>
                        <p className="stg-module-desc">{def.desc}</p>
                      </div>
                      <div className={`stg-toggle${draft[def.key] !== false ? ' on' : ''}`}
                        onClick={(e) => { e.stopPropagation(); toggleDraft(def.key); }}>
                          <div className="stg-toggle-knob" />
                        </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="stg-actions">
                <button className="btn-secondary" onClick={cancelChanges}>Cancel</button>
                <button className={`btn-primary${saveState === 'saving' ? ' btn-saving' : ''}${saveState === 'done' ? ' btn-done' : ''}`}
                  onClick={saveModules} disabled={saveState !== 'idle'}>
                  {saveState === 'idle' && 'Save Changes'}
                  {saveState === 'saving' && <span className="btn-spinner" />}
                  {saveState === 'done' && <span className="btn-check">✓</span>}
                </button>
              </div>
            </div>
          )}

          {active === 'billing' && (
            <div className="stg-panel">
              <h2>{t('settings.tabs.billing')}</h2>
              <p className="stg-subtitle stg-coming">Coming soon</p>
            </div>
          )}

          {active === 'preferences' && (
            <div className="stg-panel">
              <h2><SvcIcon name="bell" className="w-4 h-4" style={{ verticalAlign: -3, marginRight: 6 }} />{t('settings.notifPreference', { defaultValue: '通知偏好' })}</h2>
              <p className="stg-subtitle">{t('settings.notifPreferenceDesc', { defaultValue: '選擇每個模組嘅網內通知開關。關閉後該模組嘅通知唔會再彈出。' })}</p>
              {notifLoading ? (
                <div className="stg-loading">{t('settings.loading')}</div>
              ) : (
                <div className="stg-module-list">
                  {notifDefs.map(def => (
                    <div key={def.key} className="stg-module-row"
                      onClick={() => setNotifDraft(p => ({ ...p, [def.key]: !(p[def.key] ?? notifMuted[def.key]) }))}>
                      <div className="stg-module-icon">{def.icon}</div>
                      <div className="stg-module-info">
                        <p className="stg-module-name">{def.label}</p>
                        <p className="stg-module-desc">{def.desc}</p>
                      </div>
                      <div className={`stg-toggle${!(notifDraft[def.key] ?? notifMuted[def.key]) ? ' on' : ''}`}
                        onClick={(e) => { e.stopPropagation(); setNotifDraft(p => ({ ...p, [def.key]: !(p[def.key] ?? notifMuted[def.key]) })); }}>
                          <div className="stg-toggle-knob" />
                        </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="stg-actions">
                <button className="btn-secondary" onClick={() => setNotifDraft({})}>Cancel</button>
                <button className={`btn-primary${notifSaveState === 'saving' ? ' btn-saving' : ''}${notifSaveState === 'done' ? ' btn-done' : ''}`}
                  onClick={saveNotifPrefs} disabled={notifSaveState !== 'idle'}>
                  {notifSaveState === 'idle' && 'Save Changes'}
                  {notifSaveState === 'saving' && <span className="btn-spinner" />}
                  {notifSaveState === 'done' && <span className="btn-check">✓</span>}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
