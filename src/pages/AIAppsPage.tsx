import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';
import { apiClient } from '../lib/api';
import { useEscapeKey } from '../lib/useEscapeKey';
import {
  MODULES, useSecretarySettings, CONNECTED_FALLBACK, normalizeModules,
  BIBLE_BOOKS, BIBLE_CHAPTERS,
  type ModuleOptionValue, type SecretaryModule,
  type ToneId, type LangPref, type DetailLevel, type ChannelId,
} from '../hooks/useSecretarySettings';
import BookChapterSelect from '../components/BookChapterSelect';
import AddressAutocomplete from '../components/AddressAutocomplete';

// ── Working-hours slider helpers ──
const toMins = (hhmm: string): number => {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
};
const fromMins = (mins: number): string => {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
};
const clampMins = (mins: number): number => Math.max(0, Math.min(1439, mins));

const WORKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const TONES: ToneId[] = ['professional', 'friendly', 'direct', 'encouraging', 'formal'];

// bible_reading book_selection 預設組合 → BIBLE_BOOKS index 範圍（同 backend _book_range 一致）
const BIBLE_PRESET_RANGES: Record<string, [number, number]> = {
  ot_full: [0, 38],            // 創世記 → 瑪拉基書
  nt_full: [39, 65],           // 馬太福音 → 啟示錄
  ot_nt_mixed: [0, 65],        // 創世記 → 啟示錄
  psalms_proverbs: [18, 19],   // 詩篇 → 箴言
  gospels: [39, 42],           // 馬太福音 → 約翰福音
  pentateuch: [0, 4],          // 創世記 → 申命記
  pauline_epistles: [45, 57],  // 哥林多前書 → 希伯來書（同 backend BIBLE_BOOKS[45:58]）
};
const CHANNELS: { id: ChannelId; icon: string; nameKey: string; hintKey: string; comingSoon?: boolean }[] = [
  { id: 'whatsapp', icon: '💬', nameKey: 'settings.aiApps.chWhatsapp', hintKey: 'settings.aiApps.chWhatsappHint' },
  { id: 'telegram', icon: '✈️', nameKey: 'settings.aiApps.chTelegram', hintKey: 'settings.aiApps.chTelegramHint' },
  { id: 'email', icon: '📧', nameKey: 'settings.aiApps.chEmail', hintKey: 'settings.aiApps.chEmailHint' },
  { id: 'sms', icon: '💬', nameKey: 'settings.aiApps.chSms', hintKey: 'settings.aiApps.chSmsHint', comingSoon: true },
];

type SectionId = 'content' | 'hours' | 'tone' | 'channels' | 'detail' | 'model';

export default function AIAppsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { settings, syncing, update } = useSecretarySettings();
  const [section, setSection] = useState<SectionId>('content');
  const [saved, setSaved] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  // Auto-save indicator — debounced
  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 1800);
    return () => clearTimeout(timer);
  }, [saved]);

  const flashSaved = () => {
    setSavedAt(new Date());
    setSaved(true);
  };

  // ── Telegram bind wizard（2 步：① Bot Token 驗證 ② User ID 驗證 → bind）──
  const [tgBindOpen, setTgBindOpen] = useState(false);
  const [tgBotToken, setTgBotToken] = useState('');
  const [tgChatId, setTgChatId] = useState('');
  const [tgStep, setTgStep] = useState<1 | 2>(1);
  const [tgBotVerified, setTgBotVerified] = useState<string>('');   // bot username（step 1 通過）
  const [tgVerifying, setTgVerifying] = useState(false);
  const [tgChatSent, setTgChatSent] = useState(false);              // step 2 測試訊息已 send
  const [tgRemote, setTgRemote] = useState<{ status: string; bot_username?: string | null; chat_id?: string | null } | null>(null);

  useEscapeKey(() => setTgBindOpen(false), tgBindOpen);
  const [tgBusy, setTgBusy] = useState(false);
  const [tgError, setTgError] = useState('');

  // Sync telegram connection state with backend status on load
  const [tgRemoteConnected, setTgRemoteConnected] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    apiClient.get<{ status: string; bot_username?: string | null; chat_id?: string | null }>('/api/v1/telegram/status')
      .then(r => { if (!cancelled) { setTgRemoteConnected(r.status === 'active'); setTgRemote(r); } })
      .catch(() => { /* backend unavailable — keep local */ });
    return () => { cancelled = true; };
  }, []);

  // Merge backend truth for telegram connection into the rendered state
  const tgConnected = tgRemoteConnected ?? settings.channels.telegram?.connected ?? false;

  const openBindModal = () => {
    setTgError(''); setTgStep(1); setTgBotVerified(''); setTgChatSent(false); setTgBindOpen(true);
  };

  // ── Step 1 確認：verify bot token（getMe — 唔 store）──
  const verifyToken = async () => {
    if (!tgBotToken.trim()) { setTgError(t('settings.aiApps.tgErrorEmpty')); return; }
    setTgVerifying(true); setTgError('');
    try {
      const r = await apiClient.post<{ status: string; bot_username?: string }>('/api/v1/telegram/verify-token', {
        bot_token: tgBotToken.trim(),
      });
      if (r.status === 'verified' && r.bot_username) {
        setTgBotVerified(r.bot_username);
      } else {
        setTgError(t('settings.aiApps.tgTokenBad'));
      }
    } catch {
      setTgError(t('settings.aiApps.tgTokenBad'));
    } finally {
      setTgVerifying(false);
    }
  };

  // ── Step 2 確認：send test message 去 chat id（驗證 user id — 唔 store）──
  const verifyChat = async () => {
    if (!tgChatId.trim()) { setTgError(t('settings.aiApps.tgErrorEmpty')); return; }
    setTgVerifying(true); setTgError('');
    try {
      const r = await apiClient.post<{ status: string }>('/api/v1/telegram/test-chat', {
        bot_token: tgBotToken.trim(),
        chat_id: tgChatId.trim(),
      });
      if (r.status === 'sent') {
        setTgChatSent(true);
      } else {
        setTgError(t('settings.aiApps.tgChatBad'));
      }
    } catch {
      setTgError(t('settings.aiApps.tgChatBad'));
    } finally {
      setTgVerifying(false);
    }
  };

  // ── 完成：bind（store 全部 + send success message）──
  const bindTelegram = async () => {
    if (!tgBotToken.trim() || !tgChatId.trim()) { setTgError(t('settings.aiApps.tgErrorEmpty')); return; }
    setTgBusy(true); setTgError('');
    try {
      const r = await apiClient.post<{ status: string; bot_username?: string; chat_id?: string }>('/api/v1/telegram/bind', {
        bot_token: tgBotToken.trim(),
        chat_id: tgChatId.trim(),
      });
      if (r.status === 'connected') {
        setTgRemoteConnected(true);
        setTgRemote({ status: 'active', bot_username: (r.bot_username ?? tgBotVerified) || null, chat_id: (r.chat_id ?? tgChatId.trim()) || null });
        update({ channels: { ...settings.channels, telegram: { connected: true, enabled: true } } });
        setTgBindOpen(false); setTgBotToken(''); setTgChatId(''); setTgBotVerified(''); setTgChatSent(false); setTgStep(1);
        flashSaved();
      } else {
        setTgError(t('settings.aiApps.tgError'));
      }
    } catch (e: any) {
      const detail = e?.detail || e?.message || '';
      setTgError(typeof detail === 'string' && detail ? detail : t('settings.aiApps.tgError'));
    } finally {
      setTgBusy(false);
    }
  };

  const disconnectTelegram = async () => {
    setTgBusy(true); setTgError('');
    try {
      await apiClient.post('/api/v1/telegram/disconnect');
      setTgRemoteConnected(false);
      setTgRemote(null);
      update({ channels: { ...settings.channels, telegram: { connected: false, enabled: false } } });
      flashSaved();
    } catch { /* keep local */ } finally { setTgBusy(false); }
  };

  // ── Working hours (backed by settings.work_start / work_end) ──
  const startMins = toMins(settings.work_start);
  const endMins = toMins(settings.work_end);

  const setStartMins = (mins: number) => {
    const v = clampMins(mins);
    const end = toMins(settings.work_end);
    update({ work_start: fromMins(Math.min(v, Math.max(end - 30, 0))) });
  };
  const setEndMins = (mins: number) => {
    const v = clampMins(mins);
    const start = toMins(settings.work_start);
    update({ work_end: fromMins(Math.max(v, Math.min(start + 30, 1439))) });
  };
  const saveHours = () => {
    update({ work_start: settings.work_start, work_end: settings.work_end });
    flashSaved();
  };
  const resetHours = () => {
    update({ work_start: '09:00', work_end: '18:00' });
    flashSaved();
  };

  // ── Modules multi-select ──
  const connectedSet = useMemo(
    () => new Set(settings.connected_modules ?? CONNECTED_FALLBACK),
    [settings.connected_modules],
  );
  // 取消 module：傳 null 俾 backend merge（顯式刪除，唔係「冇傳 = 保留」）
  const toggleModule = (id: string) => {
    if (!connectedSet.has(id)) return; // greyed out — not connected yet
    const cur = normalizeModules(settings.modules);
    const has = id in cur;
    const next: Record<string, Record<string, ModuleOptionValue> | null> = { ...cur };
    if (has) next[id] = null;
    else next[id] = {};
    update({ modules: next as any });
    flashSaved();
  };

  // ── Module deep options popup ──
  const [editingModule, setEditingModule] = useState<SecretaryModule | null>(null);
  const [draftOpts, setDraftOpts] = useState<Record<string, ModuleOptionValue>>({});

  const openModuleEditor = (m: SecretaryModule) => {
    if (!connectedSet.has(m.id)) return;
    const cur = normalizeModules(settings.modules);
    const existing = cur[m.id] ?? {};
    const draft: Record<string, ModuleOptionValue> = {};
    for (const o of (m.options ?? [])) {
      draft[o.key] = (o.key in existing) ? existing[o.key] : o.default;
    }
    // bible_reading：book_selection 係預設組合 → 自動同步範圍顯示（custom_range 保留用家值）
    if (m.id === 'bible_reading') {
      const sel = String(draft.book_selection ?? '');
      const r = BIBLE_PRESET_RANGES[sel];
      if (r) {
        const startBook = BIBLE_BOOKS[r[0]];
        const endBook = BIBLE_BOOKS[r[1]];
        draft.start_book = startBook;
        draft.start_chapter = 1;
        draft.end_book = endBook;
        draft.end_chapter = BIBLE_CHAPTERS[endBook] ?? 1;
      }
    }
    setDraftOpts(draft);
    setEditingModule(m);
  };
  const closeModuleEditor = () => {
    setEditingModule(null);
    setDraftOpts({});
  };
  const saveModuleOptions = () => {
    if (!editingModule) return;
    const cur = normalizeModules(settings.modules);
    update({ modules: { ...cur, [editingModule.id]: draftOpts } as any });
    flashSaved();
    closeModuleEditor();
  };
  const setDraft = (key: string, value: ModuleOptionValue) => {
    setDraftOpts(prev => ({ ...prev, [key]: value }));
  };
  // bible_reading book_selection 預設組合 → 自動填開始/結束書卷+章節（custom_range 唔郁）
  const applyBiblePreset = (sel: string) => {
    const r = BIBLE_PRESET_RANGES[sel];
    if (!r) return;
    const startBook = BIBLE_BOOKS[r[0]];
    const endBook = BIBLE_BOOKS[r[1]];
    setDraft('start_book', startBook);
    setDraft('start_chapter', 1);
    setDraft('end_book', endBook);
    setDraft('end_chapter', BIBLE_CHAPTERS[endBook] ?? 1);
  };

  useEscapeKey(closeModuleEditor, !!editingModule);

  // ── Workdays ──
  const toggleWorkday = (day: string) => {
    const has = settings.workdays.includes(day);
    const next = has ? settings.workdays.filter(d => d !== day) : [...settings.workdays, day];
    update({ workdays: next });
    flashSaved();
  };

  // ── Greeting slots (editable time per slot) ──
  const updateGreetingSlot = (key: string, start: string) => {
    const next = (settings.greeting_slots ?? []).map(s => (s.key === key ? { ...s, start } : s));
    update({ greeting_slots: next });
    flashSaved();
  };
  const resetGreetings = () => {
    update({
      greeting_slots: [
        { key: 'morning', emoji: '🌅', start: '07:00' },
        { key: 'afternoon', emoji: '☀️', start: '12:00' },
        { key: 'evening', emoji: '🌆', start: '18:00' },
        { key: 'lateNight', emoji: '🌙', start: '00:00' },
      ],
    });
    flashSaved();
  };

  // ── Detail preview ──
  const detailPreview = useMemo(() => {
    const lvl = settings.detail_level;
    if (lvl === 1) return t('settings.aiApps.detailPreview1');
    if (lvl === 3) return t('settings.aiApps.detailPreview3');
    return t('settings.aiApps.detailPreview2');
  }, [settings.detail_level, t]);

  // ── AI model settings (provider / model / allow_edit) ──
  const providerModels: Record<string, string[]> = {
    deepseek: ['deepseek-chat', 'deepseek-reasoner'],
    gemini: ['gemini-2.0-flash', 'gemini-2.5-pro'],
  }
  const [aiProvider, setAiProvider] = useState('deepseek')
  const [aiModel, setAiModel] = useState('deepseek-chat')
  const [allowEdit, setAllowEdit] = useState(false)
  const [aiSaveState, setAiSaveState] = useState<'idle' | 'saving' | 'done'>('idle')

  useEffect(() => {
    apiClient.get('/api/v1/crm/module-settings')
      .then((list: any) => {
        const aiCfg = (list || []).find((m: any) => m.module_key === 'ai')
        if (aiCfg?.settings) {
          if (aiCfg.settings.provider) setAiProvider(aiCfg.settings.provider)
          if (aiCfg.settings.model) setAiModel(aiCfg.settings.model)
          if (aiCfg.settings.allow_edit !== undefined) setAllowEdit(!!aiCfg.settings.allow_edit)
        }
      })
      .catch(() => {})
  }, [])

  const handleProviderChange = (provider: string) => {
    setAiProvider(provider)
    const models = providerModels[provider]
    if (models) setAiModel(models[0])
  }

  const saveAiSettings = async () => {
    setAiSaveState('saving')
    try {
      await apiClient.put('/api/v1/crm/module-settings/ai', {
        module_key: 'ai',
        enabled: true,
        settings: { provider: aiProvider, model: aiModel, allow_edit: allowEdit },
      })
      setAiSaveState('done')
      setTimeout(() => setAiSaveState('idle'), 2000)
    } catch (e: any) {
      alert(e.detail || e.message)
      setAiSaveState('idle')
    }
  }

  // ── IM Push (AI 每日簡報推送) ──
  const [imChannels, setImChannels] = useState<Record<string, any>>({})
  const [imSaving, setImSaving] = useState(false)
  const [imSaved, setImSaved] = useState(false)
  const [imTestState, setImTestState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')

  useEffect(() => {
    apiClient.get<{ channels: Record<string, any> }>('/api/v1/im-push/prefs')
      .then(res => { if (res?.channels) setImChannels(res.channels) })
      .catch(() => {})
  }, [])

  const saveImPrefs = async (channel: string) => {
    setImSaving(true)
    try {
      await apiClient.put('/api/v1/im-push/prefs', imChannels[channel])
      setImSaved(true)
      setTimeout(() => setImSaved(false), 1600)
    } catch { /* surface via button state */ }
    setImSaving(false)
  }

  const testImPush = async (channel: string) => {
    setImTestState('sending')
    try {
      await apiClient.post('/api/v1/im-push/test', { channel })
      setImTestState('done')
      setTimeout(() => setImTestState('idle'), 2200)
    } catch {
      setImTestState('error')
      setTimeout(() => setImTestState('idle'), 3200)
    }
  }

  const nav: { id: SectionId; icon: string; labelKey: string }[] = [
    { id: 'content', icon: '📋', labelKey: 'settings.aiApps.navContent' },
    { id: 'hours', icon: '🕐', labelKey: 'settings.aiApps.navHours' },
    { id: 'tone', icon: '💬', labelKey: 'settings.aiApps.navTone' },
    { id: 'channels', icon: '🔗', labelKey: 'settings.aiApps.navChannels' },
    { id: 'detail', icon: '🔎', labelKey: 'settings.aiApps.navDetail' },
    { id: 'model', icon: '⚙️', labelKey: 'settings.aiApps.navModel' },
  ];

  // v6.66: 已選模組嘅深層選項摘要（摺疊狀態卡片底部 chips）— 最多 3 個
  const moduleSummary = (m: SecretaryModule, opts: Record<string, ModuleOptionValue>): string[] => {
    const out: string[] = [];
    for (const o of (m.options ?? [])) {
      if (o.showWhen) {
        const parentVal = opts[o.showWhen.key];
        if (String(parentVal) !== o.showWhen.equals) continue;
      }
      const v = opts[o.key];
      if (v === undefined || v === null || v === '') continue;
      if (o.type === 'single_select') {
        const c = (o.choices ?? []).find(x => x.value === v);
        if (c) out.push(t(c.labelKey));
      } else if (o.type === 'multi_select') {
        const arr = Array.isArray(v) ? v : [];
        if (arr.length) out.push(arr.map(x => t((o.choices ?? []).find(c => c.value === x)?.labelKey ?? String(x))).join('+'));
      } else if (o.type === 'number') {
        out.push(String(v));
      } else if (o.type === 'book_range' || o.type === 'text') {
        out.push(String(v));
      }
    }
    return out.slice(0, 3);
  };

  return (
    <div className="stg-page">
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">{t('settings.aiApps.title')}</span>
      </div>

      <div className="asec-header">
        <div>
          <h1>{t('settings.aiApps.title')}</h1>
          <p className="asec-subtitle">{t('settings.aiApps.subtitle')}</p>
        </div>
        <span className={`asec-save-indicator${saved ? ' active' : ''}`}>
          {saved ? <><SvcIcon name="check" size={12} /> {t('settings.aiApps.autoSaved')}</>
            : syncing ? t('settings.aiApps.saving') ?? '…'
            : savedAt ? t('settings.aiApps.savedAt') : t('settings.aiApps.allSaved')}
        </span>
      </div>

      <div className="asec-shell">
        {/* ── Sidebar nav (desktop) / tab bar (mobile) ── */}
        <nav className="asec-nav">
          {nav.map(n => (
            <button
              key={n.id}
              className={`asec-nav-item${section === n.id ? ' active' : ''}`}
              onClick={() => setSection(n.id)}
            >
              <span className="asec-nav-icon">{n.icon}</span>
              <span className="asec-nav-label">{t(n.labelKey)}</span>
            </button>
          ))}
        </nav>

        <main className="asec-content">
          {/* ══ SECTION 1: 簡報內容 ── */}
          {section === 'content' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionContent')}</h2>
                <p>{t('settings.aiApps.sectionContentDesc')}</p>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.modulesTitle')}</h3>
                <p className="asec-card-hint">{t('settings.aiApps.modulesHint')}</p>
                <div className="asec-module-grid">
                  {MODULES.map(m => {
                    const selected = (m.id in normalizeModules(settings.modules));
                    const connected = connectedSet.has(m.id);
                    const hasOpts = (m.options ?? []).length > 0;
                    return (
                      <div key={m.id} className={`asec-module-card${selected ? ' selected' : ''}${connected ? '' : ' disabled'}`}>
                        <div
                          className="asec-module-head"
                          onClick={() => connected && toggleModule(m.id)}
                          role="button"
                          tabIndex={connected ? 0 : -1}
                          aria-disabled={!connected}
                          onKeyDown={e => { if (connected && (e.key === 'Enter' || e.key === ' ')) toggleModule(m.id) }}
                        >
                          <span className="asec-module-icon">{m.icon}</span>
                          <div className="asec-module-info">
                            <strong>{t(m.nameKey)}</strong>
                            <p>{t(m.descKey)}</p>
                          </div>
                          {!connected && <span className="asec-module-tag">{t('settings.aiApps.soon')}</span>}
                          <span className={`asec-module-check${selected ? ' checked' : ''}`}>
                            {selected && <SvcIcon name="check" size={11} />}
                          </span>
                        </div>
                        {selected && hasOpts && (() => {
                          const opts = normalizeModules(settings.modules)[m.id] ?? {};
                          const chips = moduleSummary(m, opts);
                          if (!chips.length) return null;
                          return (
                            <div className="asec-module-summary-row">
                              {chips.map((c, i) => <span key={i} className="asec-module-summary-chip">{c}</span>)}
                            </div>
                          );
                        })()}
                        {connected && (
                          <div className="asec-module-foot">
                            {selected && hasOpts ? (
                              <button
                                type="button"
                                className="asec-module-settings"
                                onClick={() => openModuleEditor(m)}
                              >
                                <SvcIcon name="settings-2" size={12} /> {t('settings.aiApps.configure')}
                              </button>
                            ) : (
                              <span className="asec-module-foot-spacer" />
                            )}
                            <span className="asec-module-toggle-hint">
                              {selected ? t('settings.aiApps.clickToRemove') : t('settings.aiApps.clickToAdd')}
                            </span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

          {/* ══ Module deep-options popup ══ */}
          {editingModule && (
            <div className="modal-overlay asec-editor-overlay" onClick={closeModuleEditor}>
              <div
                className="modal asec-editor-modal"
                onClick={e => e.stopPropagation()}
                role="dialog"
                aria-modal="true"
                aria-label={t(editingModule.nameKey)}
              >
                <div className="modal-head">
                  <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>{editingModule.icon}</span> {t(editingModule.nameKey)}
                  </h3>
                  <button className="modal-x" onClick={closeModuleEditor} aria-label="Close"><SvcIcon name="x" size={18} /></button>
                </div>
                <div className="asec-editor-body">
                  {(editingModule.options ?? []).map(o => {
                    const cur = (o.key in draftOpts) ? draftOpts[o.key] : o.default;
                    // showWhen 條件渲染 — 另一 option 等於指定值先顯示
                    if (o.showWhen) {
                      const parent = (editingModule.options ?? []).find(x => x.key === o.showWhen!.key);
                      const parentVal = (o.showWhen.key in draftOpts) ? draftOpts[o.showWhen.key] : parent?.default;
                      if (String(parentVal) !== o.showWhen.equals) return null;
                    }
                    if (o.type === 'text') {
                      // v6.67: traffic origin/destination → address autocomplete
                      const isAddr = editingModule.id === 'traffic_commute' && (o.key === 'origin' || o.key === 'destination');
                      if (isAddr) {
                        return (
                          <div key={o.key} className="asec-editor-field">
                            <span className="asec-module-option-label">{t(o.labelKey)}</span>
                            <AddressAutocomplete
                              value={String(cur ?? '')}
                              onChange={v => setDraft(o.key, v)}
                              placeholder={o.placeholderKey ? t(o.placeholderKey) : ''}
                            />
                          </div>
                        );
                      }
                      return (
                        <div key={o.key} className="asec-editor-field">
                          <span className="asec-module-option-label">{t(o.labelKey)}</span>
                          <input
                            type="text"
                            className="asec-editor-input"
                            value={String(cur ?? '')}
                            placeholder={o.placeholderKey ? t(o.placeholderKey) : ''}
                            onChange={e => setDraft(o.key, e.target.value)}
                          />
                        </div>
                      );
                    }
                    if (o.type === 'number') {
                      // v6.66: start_chapter/end_chapter 已合併入 BookChapterSelect（cascading）
                      if (o.key === 'start_chapter' || o.key === 'end_chapter') return null;
                      return (
                        <div key={o.key} className="asec-editor-field">
                          <span className="asec-module-option-label">{t(o.labelKey)}</span>
                          <input
                            type="number"
                            min={1}
                            max={200}
                            className="asec-editor-input"
                            value={String(cur ?? '1')}
                            onChange={e => {
                              const v = e.target.value;
                              setDraft(o.key, v === '' ? '' : Number(v));
                            }}
                          />
                        </div>
                      );
                    }
                    if (o.type === 'book_range') {
                      // v6.66: cascading select — 書卷 + 對應章數（start_book↔start_chapter, end_book↔end_chapter）
                      const chKey = o.key === 'start_book' ? 'start_chapter' : o.key === 'end_book' ? 'end_chapter' : null;
                      const chOpt = chKey ? (editingModule.options ?? []).find(x => x.key === chKey) : null;
                      const bookVal = String(cur ?? BIBLE_BOOKS[0]);
                      const rawCh = (chKey && chKey in draftOpts) ? draftOpts[chKey] : chOpt?.default;
                      const chVal = Number(rawCh ?? 1);
                      return (
                        <div key={o.key} className="asec-editor-field">
                          <span className="asec-module-option-label">{t(o.labelKey)}</span>
                          <BookChapterSelect
                            book={bookVal}
                            chapter={chVal}
                            allowEndOfBook={o.key === 'end_book'}
                            onBookChange={b => setDraft(o.key, b)}
                            onChapterChange={c => { if (chKey) setDraft(chKey, c); }}
                          />
                        </div>
                      );
                    }
                    // single_select / multi_select → chips
                    const curArr: string[] = Array.isArray(cur) ? cur : (typeof cur === 'string' ? [cur] : []);
                    return (
                      <div key={o.key} className="asec-editor-field">
                        <span className="asec-module-option-label">{t(o.labelKey)}</span>
                        <div className="asec-module-option-choices">
                          {(o.choices ?? []).map(c => {
                            const active = o.type === 'multi_select'
                              ? curArr.includes(c.value)
                              : (cur === c.value || curArr[0] === c.value);
                            const onClick = () => {
                              if (o.type === 'multi_select') {
                                const has = curArr.includes(c.value);
                                setDraft(o.key, has ? curArr.filter(x => x !== c.value) : [...curArr, c.value]);
                              } else {
                                setDraft(o.key, c.value);
                                // bible_reading book_selection：揀預設組合 → 自動填範圍
                                if (editingModule.id === 'bible_reading' && o.key === 'book_selection') {
                                  applyBiblePreset(c.value);
                                }
                              }
                            };
                            return (
                              <button
                                key={c.value}
                                type="button"
                                className={`asec-opt-chip${active ? ' active' : ''}`}
                                onClick={onClick}
                              >
                                {c.icon && <span>{c.icon}</span>}
                                {t(c.labelKey)}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="asec-actions" style={{ marginTop: 14 }}>
                  <button className="btn-ghost" onClick={closeModuleEditor}>{t('settings.aiApps.cancel')}</button>
                  <button className="btn-primary" onClick={saveModuleOptions} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <SvcIcon name="save" size={14} /> {t('settings.aiApps.saveOptions')}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ══ SECTION 2: 工作時間 ── */}
          {section === 'hours' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionHours')}</h2>
                <p>{t('settings.aiApps.sectionHoursDesc')}</p>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.activeHours')}</h3>
                <div className="stg-hours-slider">
                  <div className="stg-hours-track">
                    <div className="stg-hours-fill" style={{ left: `${(startMins / 1440) * 100}%`, width: `${((endMins - startMins) / 1440) * 100}%` }} />
                    <input type="range" min={0} max={1439} step={30} value={startMins} onChange={e => setStartMins(Number(e.target.value))} className="stg-range stg-range-start" aria-label={t('settings.aiApps.workingStart')} />
                    <input type="range" min={0} max={1439} step={30} value={endMins} onChange={e => setEndMins(Number(e.target.value))} className="stg-range stg-range-end" aria-label={t('settings.aiApps.workingEnd')} />
                  </div>
                  <div className="stg-hours-labels">
                    <span className="stg-hours-value">{t('settings.aiApps.workingStart')}: <strong>{settings.work_start}</strong></span>
                    <span className="stg-hours-value">{t('settings.aiApps.workingEnd')}: <strong>{settings.work_end}</strong></span>
                  </div>
                </div>
                <div className="asec-actions">
                  <button className="btn-ghost" onClick={resetHours} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <SvcIcon name="rotate-ccw" size={14} /> {t('settings.aiApps.resetDefault')}
                  </button>
                  <button className="btn-primary" onClick={saveHours} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <SvcIcon name="save" size={14} /> {t('settings.aiApps.saveHours')}
                  </button>
                </div>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.greetingSchedule')}</h3>
                <p className="asec-card-hint">{t('settings.aiApps.greetingDesc')}</p>
                <div className="stg-greeting-list">
                  {(settings.greeting_slots?.length ? settings.greeting_slots : [
                    { key: 'morning', emoji: '🌅', start: '07:00' },
                    { key: 'afternoon', emoji: '☀️', start: '12:00' },
                    { key: 'evening', emoji: '🌆', start: '18:00' },
                    { key: 'lateNight', emoji: '🌙', start: '00:00' },
                  ]).map(slot => (
                    <div key={slot.key} className="stg-greeting-row">
                      <span className="stg-greeting-emoji">{slot.emoji}</span>
                      <span className="stg-greeting-name">{t('settings.aiApps.' + slot.key)}</span>
                      <input
                        type="time"
                        value={slot.start}
                        onChange={e => updateGreetingSlot(slot.key, e.target.value)}
                        className="stg-greeting-time"
                        aria-label={t('settings.aiApps.' + slot.key)}
                      />
                    </div>
                  ))}
                </div>
                <div className="asec-actions">
                  <button className="btn-ghost" onClick={resetGreetings} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    <SvcIcon name="rotate-ccw" size={14} /> {t('settings.aiApps.resetDefault')}
                  </button>
                </div>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.workdays')}</h3>
                <div className="asec-day-row">
                  {WORKDAYS.map(day => (
                    <button
                      key={day}
                      className={`asec-day-chip${settings.workdays.includes(day) ? ' active' : ''}`}
                      onClick={() => toggleWorkday(day)}
                    >
                      {t('settings.aiApps.day' + day.charAt(0).toUpperCase() + day.slice(1))}
                    </button>
                  ))}
                </div>
              </div>

              <div className="asec-card">
                <div className="asec-toggle-row">
                  <div>
                    <strong>{t('settings.aiApps.weekendMute')}</strong>
                    <p className="hint">{t('settings.aiApps.weekendMuteHint')}</p>
                  </div>
                  <label className="asec-switch">
                    <input type="checkbox" checked={settings.weekend_mute} onChange={e => { update({ weekend_mute: e.target.checked }); flashSaved(); }} />
                    <span className="asec-slider" />
                  </label>
                </div>
                <div className="asec-toggle-row">
                  <div>
                    <strong>{t('settings.aiApps.strictSilence')}</strong>
                    <p className="hint">{t('settings.aiApps.strictSilenceHint')}</p>
                  </div>
                  <label className="asec-switch">
                    <input type="checkbox" checked={settings.strict_silence} onChange={e => { update({ strict_silence: e.target.checked }); flashSaved(); }} />
                    <span className="asec-slider" />
                  </label>
                </div>
              </div>
            </section>
          )}

          {/* ══ SECTION 3: 語氣指令 ── */}
          {section === 'tone' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionTone')}</h2>
                <p>{t('settings.aiApps.sectionToneDesc')}</p>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.toneStyle')}</h3>
                <div className="asec-tone-row">
                  {TONES.map(tone => (
                    <button
                      key={tone}
                      className={`asec-tone-chip${settings.tone === tone ? ' active' : ''}`}
                      onClick={() => { update({ tone: tone as ToneId }); flashSaved(); }}
                    >
                      {t('settings.aiApps.tone' + tone.charAt(0).toUpperCase() + tone.slice(1))}
                    </button>
                  ))}
                </div>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.customInstructions')}</h3>
                <textarea
                  rows={5}
                  value={settings.instructions}
                  placeholder={t('settings.aiApps.customInstructionsPlaceholder')}
                  onChange={e => { update({ instructions: e.target.value }); flashSaved(); }}
                  className="asec-textarea"
                />
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.langPref')}</h3>
                <div className="asec-radio-row">
                  {(['zh-HK', 'zh-TW', 'en'] as LangPref[]).map(lang => (
                    <label key={lang} className="asec-radio">
                      <input
                        type="radio"
                        name="langPref"
                        checked={settings.lang_pref === lang}
                        onChange={() => { update({ lang_pref: lang }); flashSaved(); }}
                      />
                      {t('settings.aiApps.lang' + lang)}
                    </label>
                  ))}
                </div>
              </div>
            </section>
          )}

          {/* ══ SECTION 4: 通訊整合 ── */}
          {section === 'channels' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionChannels')}</h2>
                <p>{t('settings.aiApps.sectionChannelsDesc')}</p>
              </div>

              <div className="asec-channel-list">
                {CHANNELS.map(ch => {
                  const isTelegram = ch.id === 'telegram';
                  const connected = isTelegram ? tgConnected : settings.channels[ch.id]?.connected;
                  const enabled = settings.channels[ch.id]?.enabled ?? false;
                  const state = { connected, enabled };
                  return (
                    <div key={ch.id} className={`asec-channel-card${connected ? ' connected' : ''}${ch.comingSoon ? ' disabled' : ''}`}>
                      <div className="asec-channel-info">
                        <span className="asec-channel-icon">{ch.icon}</span>
                        <div>
                          <strong>{t(ch.nameKey)}</strong>
                          <p className="hint">
                            {ch.comingSoon
                              ? t('settings.aiApps.comingSoon')
                              : connected
                                ? t('settings.aiApps.chConnected')
                                : t('settings.aiApps.chNotConnected')}
                          </p>
                        </div>
                      </div>
                      {ch.comingSoon ? (
                        <button className="btn-ghost" disabled style={{ opacity: 0.5, cursor: 'not-allowed' }}>{t('settings.aiApps.comingSoon')}</button>
                      ) : connected ? (
                        <div className="asec-channel-actions">
                          <label className="asec-switch">
                            <input type="checkbox" checked={enabled} onChange={e => { update({ channels: { ...settings.channels, [ch.id]: { ...state, enabled: e.target.checked } } }); flashSaved(); }} />
                            <span className="asec-slider" />
                          </label>
                          {isTelegram && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                          <span className="hint" style={{ fontSize: 12, color: 'var(--color-text-faint)' }}>
                            {t('settings.aiApps.tgStatusDetail', { bot: tgRemote?.bot_username ?? '', id: tgRemote?.chat_id ?? '' })}
                          </span>
                          <button className="btn-ghost" onClick={disconnectTelegram} disabled={tgBusy}>
                            {t('settings.aiApps.chDisconnect')}
                          </button>
                        </div>
                      )}
                        </div>
                      ) : isTelegram ? (
                        <button className="btn-primary" onClick={openBindModal}>
                          {t('settings.aiApps.chConnect')}
                        </button>
                      ) : (
                        <button className="btn-primary" onClick={() => { update({ channels: { ...settings.channels, [ch.id]: { connected: true, enabled: true } } }); flashSaved(); }}>
                          {t('settings.aiApps.chConnect')}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* ── Telegram bind wizard modal（2 步）── */}
              {tgBindOpen && (
                <div className="modal-overlay" onClick={() => setTgBindOpen(false)}>
                  <div className="modal" style={{ maxWidth: 480 }} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={t('settings.aiApps.chTelegram')}>
                    <div className="modal-head">
                      <h2>{t('settings.aiApps.tgBindTitle')}</h2>
                      <button className="modal-x" onClick={() => setTgBindOpen(false)} aria-label="Close"><SvcIcon name="x" size={18} /></button>
                    </div>
                    <div className="modal-body">
                      {/* 步驟指示 */}
                      <p className="hint" style={{ marginTop: 0, fontWeight: 600 }}>
                        {t('settings.aiApps.tgStepLabel', { step: tgStep })} — {tgStep === 1 ? t('settings.aiApps.tgStep1Title') : t('settings.aiApps.tgStep2Title')}
                      </p>

                      {tgStep === 1 && (
                        <>
                          {/* Step 1 教學 */}
                          <div style={{ background: 'var(--color-surface-2, #f6f7f9)', borderRadius: 10, padding: '10px 14px', marginBottom: 12, whiteSpace: 'pre-line', fontSize: 13, lineHeight: 1.6 }}>
                            {t('settings.aiApps.tgStep1Help')}
                          </div>
                          <label className="asec-field">
                            <span>{t('settings.aiApps.tgBotToken')}</span>
                            <input type="password" value={tgBotToken} onChange={e => { setTgBotToken(e.target.value); setTgBotVerified(''); }} placeholder={t('settings.aiApps.tgTokenPlaceholder')} autoComplete="off" />
                          </label>
                          {tgBotVerified && (
                            <p style={{ color: '#34d399', fontWeight: 600, fontSize: 13, margin: '8px 0 0' }}>
                              {t('settings.aiApps.tgTokenOk', { bot: tgBotVerified })}
                            </p>
                          )}
                        </>
                      )}

                      {tgStep === 2 && (
                        <>
                          {/* Step 2 教學 */}
                          <div style={{ background: 'var(--color-surface-2, #f6f7f9)', borderRadius: 10, padding: '10px 14px', marginBottom: 12, whiteSpace: 'pre-line', fontSize: 13, lineHeight: 1.6 }}>
                            {t('settings.aiApps.tgStep2Help')}
                          </div>
                          <label className="asec-field">
                            <span>{t('settings.aiApps.tgChatId')}</span>
                            <input type="text" value={tgChatId} onChange={e => { setTgChatId(e.target.value); setTgChatSent(false); }} placeholder={t('settings.aiApps.tgUserIdPlaceholder')} autoComplete="off" />
                          </label>
                          {tgChatSent && (
                            <p style={{ color: '#34d399', fontWeight: 600, fontSize: 13, margin: '8px 0 0' }}>
                              {t('settings.aiApps.tgChatOk')}
                            </p>
                          )}
                        </>
                      )}

                      {tgError && <p className="asec-error">{tgError}</p>}
                    </div>
                    <div className="modal-foot" style={{ flexWrap: 'wrap', gap: 8 }}>
                      {tgStep === 1 ? (
                        <>
                          <button className="btn-secondary" onClick={() => setTgBindOpen(false)}>{t('common.cancel')}</button>
                          {tgBotVerified ? (
                            <button className="btn-primary" onClick={() => { setTgError(''); setTgStep(2); }}>{t('settings.aiApps.tgNext')}</button>
                          ) : (
                            <button className="btn-primary" onClick={verifyToken} disabled={tgVerifying || !tgBotToken.trim()}>
                              {tgVerifying ? t('settings.aiApps.tgVerifying') : t('settings.aiApps.tgVerifyToken')}
                            </button>
                          )}
                        </>
                      ) : (
                        <>
                          <button className="btn-secondary" onClick={() => { setTgError(''); setTgStep(1); }}>{t('settings.aiApps.tgBack')}</button>
                          {!tgChatSent && (
                            <button className="btn-primary" onClick={verifyChat} disabled={tgVerifying || !tgChatId.trim()}>
                              {tgVerifying ? t('settings.aiApps.tgVerifying') : t('settings.aiApps.tgVerifyChat')}
                            </button>
                          )}
                          <button className="btn-primary" onClick={bindTelegram} disabled={tgBusy || !tgChatSent}>
                            {tgBusy ? t('settings.aiApps.tgFinishBusy') : t('settings.aiApps.tgFinish')}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* ── 通知與整合 — AI 每日簡報推送 ── */}
              <div className="asec-card" style={{ marginTop: 28 }}>
                <h3>📲 {t('settings.aiApps.notifTitle')}</h3>
                <p className="asec-card-hint">{t('settings.aiApps.notifDesc')}</p>

                {Object.keys(imChannels).length === 0 && (
                  <div className="asec-card-hint" style={{ padding: '10px 0' }}>
                    {t('settings.aiApps.notifEmpty')}
                  </div>
                )}

                {Object.entries(imChannels).map(([ch, pref]: [string, any]) => (
                  <div key={ch} className="asec-channel-card" style={{ marginTop: 10, flexDirection: 'column', alignItems: 'stretch' }}>
                    <div className="asec-channel-info">
                      <span className="asec-channel-icon">{ch === 'whatsapp' ? '💬' : '✈️'}</span>
                      <div>
                        <strong>{ch === 'whatsapp' ? 'WhatsApp' : 'Telegram'}</strong>
                        <p className="hint" style={{ fontWeight: 600, color: pref.enabled ? '#34d399' : 'var(--color-text-faint)' }}>
                          {pref.enabled ? t('settings.aiApps.notifEnabled') : t('settings.aiApps.notifDisabled')}
                        </p>
                      </div>
                      <label className="asec-switch" style={{ marginLeft: 'auto' }}>
                        <input type="checkbox" checked={!!pref.enabled}
                          onChange={() => setImChannels({ ...imChannels, [ch]: { ...pref, enabled: !pref.enabled } })} />
                        <span className="asec-slider" />
                      </label>
                    </div>

                    <div className="asec-day-row" style={{ marginTop: 12 }}>
                      {(['morning', 'noon', 'evening'] as const).map(s => (
                        <label key={s}
                          className={`asec-day-chip${pref.slots?.[s] ? ' active' : ''}`}
                          style={{ cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={!!pref.slots?.[s]}
                            onChange={() => setImChannels({
                              ...imChannels,
                              [ch]: { ...pref, slots: { ...pref.slots, [s]: !pref.slots?.[s] } },
                            })}
                            style={{ display: 'none' }}
                          />
                          {s === 'morning' ? '☀️ ' + t('settings.aiApps.slotMorning') : s === 'noon' ? '☕ ' + t('settings.aiApps.slotNoon') : '🌙 ' + t('settings.aiApps.slotEvening')}
                        </label>
                      ))}
                    </div>

                    <label className="asec-toggle-row" style={{ marginTop: 12, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={!!pref.weekend_mute}
                        onChange={() => setImChannels({ ...imChannels, [ch]: { ...pref, weekend_mute: !pref.weekend_mute } })}
                        style={{ accentColor: 'var(--color-primary)' }}
                      />
                      <span style={{ fontSize: 12.5 }}>{t('settings.aiApps.notifWeekendMute')}</span>
                    </label>

                    <div className="asec-actions" style={{ marginTop: 14 }}>
                      <button className="btn-primary" onClick={() => saveImPrefs(ch)} disabled={imSaving}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, padding: '7px 14px' }}>
                        💾 {t('settings.aiApps.notifSave')}
                      </button>
                      <button className="btn-ghost" onClick={() => testImPush(ch)} disabled={imTestState === 'sending'}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, padding: '7px 14px' }}>
                        {imTestState === 'sending' ? t('settings.aiApps.notifSending') + '…' : '📨 ' + t('settings.aiApps.notifTest')}
                      </button>
                      {imSaved && <span style={{ fontSize: 12, fontWeight: 600, color: '#34d399' }}>✓ {t('settings.aiApps.notifSaved')}</span>}
                      {imTestState === 'done' && <span style={{ fontSize: 12, fontWeight: 600, color: '#34d399' }}>✓ {t('settings.aiApps.notifSent')}</span>}
                      {imTestState === 'error' && <span style={{ fontSize: 12, fontWeight: 600, color: '#f87171' }}>⚠️ {t('settings.aiApps.notifFail')}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ══ SECTION 5: 資料詳細度 ── */}
          {section === 'detail' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionDetail')}</h2>
                <p>{t('settings.aiApps.sectionDetailDesc')}</p>
              </div>

              <div className="asec-card">
                <div className="asec-detail-wrap">
                  <input
                    type="range" min={1} max={3} step={1} value={settings.detail_level}
                    onChange={e => { update({ detail_level: Number(e.target.value) as DetailLevel }); flashSaved(); }}
                    className="asec-detail-slider"
                  />
                  <div className="asec-detail-labels">
                    <span className={settings.detail_level === 1 ? 'active' : ''}>{t('settings.aiApps.detailBrief')}</span>
                    <span className={settings.detail_level === 2 ? 'active' : ''}>{t('settings.aiApps.detailStandard')}</span>
                    <span className={settings.detail_level === 3 ? 'active' : ''}>{t('settings.aiApps.detailFull')}</span>
                  </div>
                </div>
                <div className="asec-detail-preview">{detailPreview}</div>
              </div>
            </section>
          )}

          {/* ══ SECTION 6: AI 設定（供應商 / 模型 / API） ── */}
          {section === 'model' && (
            <section className="asec-section">
              <div className="asec-section-title">
                <h2>{t('settings.aiApps.sectionModel')}</h2>
                <p>{t('settings.aiApps.sectionModelDesc')}</p>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.modelProvider')}</h3>
                <select className="asec-select" value={aiProvider}
                  onChange={e => handleProviderChange(e.target.value)}>
                  <option value="deepseek">DeepSeek</option>
                  <option value="gemini">Gemini</option>
                </select>
              </div>

              <div className="asec-card">
                <h3>{t('settings.aiApps.modelName')}</h3>
                <select className="asec-select" value={aiModel}
                  onChange={e => setAiModel(e.target.value)}>
                  {providerModels[aiProvider]?.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              <div className="asec-card">
                <div className="asec-toggle-row">
                  <div>
                    <strong>{t('settings.aiApps.allowEdit')}</strong>
                    <p className="hint">{t('settings.aiApps.allowEditHint')}</p>
                  </div>
                  <label className="asec-switch">
                    <input type="checkbox" checked={allowEdit}
                      onChange={e => setAllowEdit(e.target.checked)} />
                    <span className="asec-slider" />
                  </label>
                </div>
              </div>

              <div className="asec-actions">
                <button className={`btn-primary${aiSaveState === 'saving' ? ' btn-saving' : ''}${aiSaveState === 'done' ? ' btn-done' : ''}`}
                  onClick={saveAiSettings} disabled={aiSaveState !== 'idle'}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {aiSaveState === 'idle' && t('settings.aiApps.saveModel')}
                  {aiSaveState === 'saving' && <><span className="btn-spinner" /> {t('settings.aiApps.saving')}</>}
                  {aiSaveState === 'done' && <><SvcIcon name="check" size={14} /> {t('settings.aiApps.modelSaved')}</>}
                </button>
              </div>

            </section>
          )}
        </main>
      </div>
    </div>
  );
}
