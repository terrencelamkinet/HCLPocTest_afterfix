import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import i18n from '../../i18n/config';
import { apiClient } from '../../lib/api';
import FollowUpChips from '../ai/chat/core/FollowUpChips';
import MarkdownMessage from '../MarkdownRenderer';
import ActionPreviewModal from '../ActionPreviewModal';
// [detail-v3] summary 改 chat message — EntitySummaryCard 唔再喺 AiSearchPanel 用
import { PencilLine, CalendarClock, Maximize2, Plus, Trash2 } from 'lucide-react'
import SvcIcon from '../../components/SvcIcon'

/**
 * AI & Search dual panel — center nav button（v6.71）
 * Tab 1 問 AI：真 chat — sessions / streaming / citations / follow-ups
 *   （邏輯同 ChatboxPanel 一致，重用 /api/v1/ai/chat/stream + cb-* 樣式）
 * Tab 2 搜尋：真 global search（debounce /api/v1/crm/search → 導航）
 */

export interface SearchResult { id: string; type: string; title: string; subtitle?: string; icon: string; }

interface Props {
  open: boolean;
  onClose: () => void;
  onScanCard: () => void;
  /* SPEC detail-pages-polish T1: mobile detail Ask AI → 開 panel（MobileNavHost 傳） */
  onRequestOpen?: () => void;
}

const TYPE_EMOJI: Record<string, string> = {
  contact: '👤', company: '🏢', task: '✅',
  project: '📁', touchpoint: '🔄', note: '📝', event: '📅',
};

/* ── Chat types（同 ChatboxPanel 一致）── */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  citations?: CitationSource[];
  followups?: string[];
}
interface CitationSource { id: string; type: string; title: string; snippet: string; updated_at?: string }
interface SessionItem { session_id: string; title: string; status?: string; is_pinned?: boolean; created_at?: string }

let msgCounter = 0;
function nextId() { msgCounter += 1; return `msg_${Date.now()}_${msgCounter}`; }
function userMessage(content: string): ChatMessage { return { id: nextId(), role: 'user', content, timestamp: Date.now() }; }
function assistantMessage(content: string, followups?: string[]): ChatMessage {
  return { id: nextId(), role: 'assistant', content, timestamp: Date.now(), ...(followups?.length ? { followups } : {}) };
}

const GREETING = "Hi! I'm Penguin AI. How can I help you today?";
const CAPABILITIES = [
  { icon: Plus,        title: i18n.t('ai.capabilityAdd', { defaultValue: '新增資料' }), desc: i18n.t('ai.capabilityAddDesc', { defaultValue: '「幫我新增一個聯絡人…」— AI 直接寫入你嘅 tenant 資料庫' }) },
  { icon: PencilLine,  title: i18n.t('ai.capabilityEdit', { defaultValue: '修改資料' }), desc: i18n.t('ai.capabilityEditDesc', { defaultValue: '「將 Kong API 專案到期日改成 9月20日」— AI 直接更新現有記錄' }) },
  { icon: Trash2,      title: i18n.t('ai.capabilityDelete', { defaultValue: '刪除資料' }), desc: i18n.t('ai.capabilityDeleteDesc', { defaultValue: '「刪除 XXX 呢個聯絡人」— AI 會先確認再執行刪除' }) },
  { icon: CalendarClock, title: i18n.t('ai.capabilityCalendar', { defaultValue: '行事曆主動提問' }), desc: i18n.t('ai.capabilityCalendarDesc', { defaultValue: 'AI 自動掃描你嘅日程，細節不足嘅活動會主動問你補充' }) },
];
const QUICK_CHIPS = [i18n.t('ai.quickTodo', { defaultValue: '總結今日待辦' }), i18n.t('ai.quickEmail', { defaultValue: '幫我起草跟進 email' }), i18n.t('ai.quickRisk', { defaultValue: '分析專案風險' })];

export default function AiSearchPanel({ open, onClose, onRequestOpen }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  /* SPEC ai-butler-v2 T3: overview（管家概覽 — default）/ notifications（通知 tab）/
     ai（問 AI chat）/ search（搜尋） */
  const [mode, setMode] = useState<'overview' | 'notifications' | 'ai' | 'search'>('overview');
  const [closing, setClosing] = useState(false);
  // 通知/概覽 data（中央化通知 — 同 MobileBottomNav badge 同一來源）
  const [notifs, setNotifs] = useState<{ id: string; title: string; body?: string; status?: string; created_at?: string; source_record_type?: string; source_record_id?: string; action_url?: string }[]>([]);
  /* AI action draft（add items 等）→ confirm modal（同 desktop ChatboxPanel 一致） */
  // v2 (2026-09-09): batch drafts（一個 stream 多個 action events）
  const [actionQueue, setActionQueue] = useState<Array<{ tool_key: string; params: Record<string, unknown>; action_id?: string }>>([]);
  /* 2026-09-10 Terrence: subscription 狀態已移除（Pro badge 唔再喺 AI panel 顯示） */
  const [unread, setUnread] = useState(0);
  const [dueTasks, setDueTasks] = useState<{ id: string; title: string; due_date?: string }[]>([]);
  const fetchOverviewData = useCallback(async () => {
    try {
      const [n, u, td] = await Promise.all([
        apiClient.get<{ items?: { id: string; title: string; body?: string; status?: string; created_at?: string }[] }>('/api/v1/notifications?page=1&page_size=10'),
        apiClient.get<{ unread_count: number }>('/api/v1/notifications/unread-count'),
        apiClient.get<{ items?: { id: string; title: string; due_date?: string }[] }>('/api/v1/crm/todo/tasks?limit=100&status=pending'),
      ]);
      setNotifs(n?.items || []);
      setUnread(u?.unread_count || 0);
      const hkt = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
      setDueTasks((td?.items || []).filter(x => x.due_date && String(x.due_date).slice(0, 10) === hkt));
    } catch { /* panel 唔可以因 data fail 而爛 */ }
  }, []);
  // 每次打開 → 管家概覽先（管家先匯報後聽命 — Q3b-A）+ 刷新通知 data
  useEffect(() => {
    if (open) { setMode('overview'); fetchOverviewData(); }
  }, [open, fetchOverviewData]);

  /* ── SPEC detail-v3: Ask AI → 開新 chat + AI 對話式 summary ── */
  const pendingEntity = useRef<{ type?: string; name?: string; id?: string } | null>(null);
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!detail?.context) return;
      const c = detail.context;
      const etype = (c.type || c.entity_type || '').toLowerCase();
      const eid = c.id;
      if (!eid) return;
      pendingEntity.current = { type: etype, name: c.name || c.company_name || c.title || '此項目', id: eid };
      if (onRequestOpen) {
        onRequestOpen();
        // open effect 會 reset 去 overview — 下個 tick 跳去 AI tab（chat + summary）
        setTimeout(() => setMode('ai'), 40);
      }
      if (etype && ['company', 'contact', 'project', 'task', 'touchpoint'].includes(etype)) {
        // SPEC detail-v3: Ask AI = 開一個新 chat — AI 摘要以對話 message 展示（唔再係 pinned 卡）
        apiClient.post<{ summary: string; tags: { label: string; kind: string }[] }>('/api/v1/ai/entity-insight', { entity_type: etype, entity_id: eid })
          .then(r => {
            const name = pendingEntity.current?.name || '此項目';
            const tags = r?.tags || [];
            const tagLines = tags.map((tg: { label: string; kind: string }) =>
              `${tg.kind === 'opportunity' ? '🎯' : tg.kind === 'risk' ? '⚠️' : 'ℹ️'} ${tg.label}`).join('\n');
            const content = [
              `我幫你整理咗 **${name}** 嘅 AI 摘要：`,
              '',
              r?.summary || '暫時未有摘要 — 可以直接問我',
              tagLines ? `\n${tagLines}` : '',
              '',
              '_仲想知多啲，直接喺度問我 👍_',
            ].join('\n');
            /* SPEC mobile-crm-svg-uiux §8.2: quick actions 做 chat suggestion chips（click → send） */
            const followups = [
              '摘要此聯絡人',
              '草擬跟進訊息',
              '建議下一步行動',
              '搵缺漏嘅聯絡資料',
            ];
            setMessages([assistantMessage(content, followups)]);
            setSessionId(null);
          })
          .catch(() => { /* insight 失敗 — chat 維持原狀 */ });
      }
    };
    window.addEventListener('nexus:open-ai-panel', handler);
    return () => window.removeEventListener('nexus:open-ai-panel', handler);
  }, [onRequestOpen]);
  /* 2026-09-07 fix: 睇完通知 → 通知 MobileBottomNav bell badge 即時 refresh（unread state 分散兩 component — 冇 sync 就永遠唔清） */
  const notifReadEvent = () => { try { window.dispatchEvent(new Event('nexus:notif-read')); } catch { /* noop */ } };
  const markAllRead = async () => {
    try { await apiClient.post('/api/v1/notifications/read-all'); setUnread(0); setNotifs(prev => prev.map(x => ({ ...x, status: 'READ' }))); notifReadEvent(); } catch { /* ignore */ }
  };
  const markRead = async (id: string) => {
    try { await apiClient.patch(`/api/v1/notifications/${id}/read`, {}); setUnread(prev => Math.max(0, prev - 1)); setNotifs(prev => prev.map(x => x.id === id ? { ...x, status: 'READ' } : x)); notifReadEvent(); } catch { /* ignore */ }
  };
  /* SPEC ai-butler-v2: 通知 → 相關記錄頁 deep link（快速處理） */
  const notifTarget = (x: { action_url?: string; source_record_type?: string; source_record_id?: string }): string | null => {
    if (x.action_url) return x.action_url;
    if (!x.source_record_id) return null;
    switch (x.source_record_type) {
      case 'task': return `/tasks/${x.source_record_id}`;
      case 'project': return `/projects/${x.source_record_id}`;
      case 'contact': return `/contacts/${x.source_record_id}`;
      case 'calendar_event': return `/l/m/${x.source_record_id}`;
      default: return null;
    }
  };
  const openNotif = async (x: { id: string; status?: string; action_url?: string; source_record_type?: string; source_record_id?: string }) => {
    // 未讀 → 先標已讀（睇咗當處理咗）；有連結 → 入記錄頁
    if (x.status !== 'READ') await markRead(x.id);
    const target = notifTarget(x);
    if (target) { handleClose(); navigate(target); }
  };

  // ── Chat state ──
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  /* 2026-09-10 Terrence: 相機 / 相簿 → 傳圖俾 AI（A+B）
     —— 上傳去 /api/v1/ai/vision（Qwen3-VL）攞描述，放入輸入框，用戶可加問題再送 chat */
  const [visionBusy, setVisionBusy] = useState(false);
  const camInputRef = useRef<HTMLInputElement>(null);
  const galInputRef = useRef<HTMLInputElement>(null);
  const uploadImage = useCallback(async (f: File) => {
    if (!f) return;
    setVisionBusy(true);
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await apiClient.postForm<{ text?: string }>('/api/v1/ai/vision', fd);
      const desc = (res as { text?: string } | undefined)?.text || '';
      if (desc) setInput(prev => (prev ? prev + '\n' : '') + desc);
      else setError('未能分析圖片，請再試。');
    } catch {
      setError('圖片分析失敗，請再試。');
    } finally {
      setVisionBusy(false);
    }
  }, []);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionList, setSessionList] = useState<SessionItem[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ── Search state ──
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchType, setSearchType] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const SEARCH_FILTERS = [
    { key: '', label: t('searchTab.all', { defaultValue: '全部' }) },
    { key: 'contact', label: t('searchTab.contact', { defaultValue: '聯絡人' }) },
    { key: 'company', label: t('searchTab.company', { defaultValue: '公司' }) },
    { key: 'task', label: t('searchTab.task', { defaultValue: '任務' }) },
    { key: 'project', label: t('searchTab.project', { defaultValue: '專案' }) },
    { key: 'touchpoint', label: t('searchTab.touchpoint', { defaultValue: '互動' }) },
    { key: 'note', label: t('searchTab.note', { defaultValue: '筆記' }) },
  ];

  /* ── Sessions ── */
  const switchSession = useCallback(async (sid: string) => {
    setSessionId(sid);
    setLoadingSession(true);
    setMessages([]);
    try {
      const resp = await apiClient.get<{ messages: any[] }>(`/api/v1/ai/sessions/${sid}/messages`);
      const msgs = resp?.messages || [];
      setMessages(msgs.length
        ? msgs.map((m: any) => ({ id: m.id, role: m.role, content: m.content, timestamp: new Date(m.created_at || Date.now()).getTime() }))
        : [assistantMessage(GREETING)]);
    } catch {
      setMessages([assistantMessage(GREETING)]);
    } finally {
      setLoadingSession(false);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    setLoadingSession(true);
    try {
      const resp = await apiClient.get<{ sessions: SessionItem[] }>('/api/v1/ai/sessions');
      const list = resp?.sessions || [];
      setSessionList(list);
      // v6.90: 每次開 panel 都係新對話 — 唔好自動 switch 去舊 session。
      // 之前自動 load active/first session → AI 帶住舊 context 答非所問
      // （「佢有佢講」）。舊對話留喺 session chips 俾用戶自己揀。
      setSessionId(null);
      setMessages([assistantMessage(GREETING)]);
    } catch {
      setMessages([assistantMessage(GREETING)]);
    } finally {
      setLoadingSession(false);
    }
  }, []);

  const createNewSession = () => {
    abortRef.current?.abort();
    setSessionId(null);
    setMessages([]);
    setError(null);
  };

  /* ── Streaming（同 ChatboxPanel doStream 一致）── */
  const doStream = useCallback(async (text: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);
    setIsStreaming(true);
    setError(null);
    try {
      const resp = await fetch('/api/v1/ai/chat/stream', {
        method: 'POST',
        // 2026-09-15 SAST：session 喺 httpOnly cookie（SameSite=Lax + 同源）
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ messages: [{ role: 'user', content: text }], session_id: sessionId || null, agent_id: null }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
        throw new Error(errBody.detail || `Request failed with status ${resp.status}`);
      }
      const reader = resp.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';
      let fullReply = '';
      let newSessionId: string | null = null;
      const msgCitations: CitationSource[] = [];
      let msgFollowups: string[] = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n').map(l => l.replace('\r', ''));
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.text !== undefined) { fullReply += data.text; setStreamingContent(fullReply); }
            if (data.session_id) newSessionId = data.session_id;
            if (data.citations && Array.isArray(data.citations)) {
              const existingIds = new Set(msgCitations.map(c => c.id));
              for (const cit of data.citations) {
                if (!existingIds.has(cit.id)) { msgCitations.push(cit as CitationSource); existingIds.add(cit.id); }
              }
            }
            if (data.followups && Array.isArray(data.followups)) msgFollowups = data.followups.map(String).slice(0, 3);
            if (data.message) setError(data.message);
            /* AI action preview（add contact/task 等 — 先顯示完整資料，用戶 confirm 先執行） */
            if (data.action_id && data.tool_key) {
              const na = { tool_key: data.tool_key, params: data.params || {}, action_id: data.action_id };
              setActionQueue(prev => (prev.some(a => a.action_id === data.action_id) ? prev : [...prev, na]));
            }
          } catch { /* skip */ }
        }
      }
      if (fullReply) {
        const reply: ChatMessage = {
          ...assistantMessage(fullReply),
          citations: msgCitations.length ? msgCitations : undefined,
          followups: msgFollowups.length ? msgFollowups : undefined,
        };
        setMessages(prev => [...prev, reply]);
      }
      if (newSessionId && newSessionId !== sessionId) setSessionId(newSessionId);
      setStreamingContent('');
      const resp2 = await apiClient.get<{ sessions: SessionItem[] }>('/api/v1/ai/sessions').catch(() => null);
      if (resp2?.sessions) setSessionList(resp2.sessions);
    } catch (e: any) {
      if (e.name !== 'AbortError') setError(e?.message || i18n.t('ai.requestFailed', { defaultValue: '請求失敗，請再試' }));
    } finally {
      setIsStreaming(false);
      setIsLoading(false);
      setStreamingContent('');
      abortRef.current = null;
    }
  }, [sessionId]);

  const sendMessage = useCallback(async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || isLoading || isStreaming) return;
    setMessages(prev => [...prev, userMessage(content)]);
    setInput('');
    await doStream(content);
  }, [input, isLoading, isStreaming, doStream]);

  /* ── Open/close reset ── */
  useEffect(() => {
    if (open) {
      setClosing(false);
      // SPEC ai-butler-v2 T3: default mode 由上面 overview effect 控制（唔好喺度覆寫）
      loadSessions();
      setTimeout(() => document.querySelector<HTMLInputElement>('.aisp-input')?.focus(), 300);
    } else {
      abortRef.current?.abort();
      setQuery(''); setResults([]);
    }
  }, [open, loadSessions]);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    const el = scrollRef.current;
    if (el) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [messages, isStreaming, streamingContent, isLoading]);

  /* ── Debounced search ── */
  useEffect(() => {
    if (mode !== 'search' || !open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    if (q.length < 2) { setResults([]); setSearching(false); return; }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const typesParam = searchType ? `&types=${encodeURIComponent(searchType)}` : '';
        const data = await apiClient.get<{ results: any[] }>(`/api/v1/crm/search?q=${encodeURIComponent(q)}&limit=10${typesParam}`);
        setResults((data?.results || []).filter((r: any) => r.type !== 'deal').map((r: any) => ({
          id: String(r.id), type: r.type, title: r.label, subtitle: r.sub,
          icon: TYPE_EMOJI[r.type] || '📄',
        })));
      } catch { setResults([]); }
      setSearching(false);
    }, 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, mode, open, searchType]);

  const handleClose = () => {
    if (closing) return;
    setClosing(true);
    abortRef.current?.abort();
    setTimeout(() => {
      // Reset closing BEFORE onClose — otherwise a quick reopen renders one
      // frame with the .closing class (opacity 0) = open flash/flicker.
      setClosing(false);
      onClose();
    }, 200);
  };

  const openFullscreen = () => {
    handleClose();
    // v6.76: 跟當前 tab — AI tab 去 AI 頁面，搜尋 tab 去搜尋頁面
    // SPEC ai-butler-v2 T3: overview/notifications → AI 頁面（通知有自己 full page）
    navigate(mode === 'search' ? '/search' : mode === 'notifications' ? '/notifications' : '/ai');
  };

  /* v6.82: lock background scroll while panel is open */
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  if (!open) return null;

  const goResult = (r: SearchResult) => {
    const map: Record<string, string> = { contact: 'contacts', company: 'companies', task: 'tasks', project: 'projects', touchpoint: 'touchpoints' };
    handleClose();
    navigate(`/${map[r.type] || 'dashboard'}/${r.id}`);
  };

  const emptyChat = messages.length === 0 && !loadingSession && !isStreaming;

  return createPortal(
    <div className={`aisp-overlay ${closing ? 'closing' : ''}`} onClick={handleClose}>
      <div className={`aisp-panel ${closing ? 'closing' : ''}`} onClick={e => e.stopPropagation()}>
        <div className="aisp-handle" />
        <div className="aisp-head">
          <h3>{t('ai.aiButler', { defaultValue: '企鵝管家' })}</h3>
          {/* 2026-09-10 Terrence: 3 個功能掣由右邊移去標題側 —
              Notification = icon only / Search = icon only / Ask AI = icon + 文字 */}
          <div className="aisp-func-group">
            <button type="button" className={`aisp-icon-btn ${mode === 'notifications' ? 'active' : ''}`} onClick={() => setMode('notifications')} aria-label={t('nav.notifications', { defaultValue: '通知' })} title={t('nav.notifications', { defaultValue: '通知' })}>
              <SvcIcon name="bell" size={16} />
              {unread > 0 && <span className="aisp-icon-badge">{unread > 9 ? '9+' : unread}</span>}
            </button>
            <button type="button" className={`aisp-icon-btn ${mode === 'search' ? 'active' : ''}`} onClick={() => setMode('search')} aria-label={t('ai.tabSearch', { defaultValue: '搜尋' })} title={t('ai.tabSearch', { defaultValue: '搜尋' })}>
              <SvcIcon name="search" size={16} />
            </button>
            <button type="button" className={`aisp-func-ask ${mode === 'ai' ? 'active' : ''}`} onClick={() => setMode('ai')}>
              <SvcIcon name="penguin-ai" size={15} />
              <span>Ask AI</span>
            </button>
          </div>
          <div className="aisp-head-actions">
            <button type="button" className="aisp-close" onClick={openFullscreen} aria-label={t('ai.fullscreenSearch', { defaultValue: '全螢幕搜尋' })}><Maximize2 /></button>
            <button type="button" className="aisp-close" onClick={handleClose} aria-label="Close"><SvcIcon name="x" /></button>
          </div>
        </div>

        {/* SPEC ai-butler-v2 T3: 管家概覽 — 管家先匯報後聽命（Q3b-A） */}
        {mode === 'overview' && (
          <div className="aisp-overview">
            <div className="aisp-ov-greet">
              <div className="aisp-ov-hello">{(() => {
                const h = new Date(Date.now() + 8 * 3600 * 1000).getUTCHours();
                return h < 11 ? '早晨好！' : h < 18 ? '午安！' : '晚上好！';
              })()}</div>
              <div className="aisp-ov-sub">
                {unread + dueTasks.length > 0
                  ? `今日有 ${unread + dueTasks.length} 件事要跟進 — 我幫你睇實。`
                  : '今日暫時冇 pending 事項，一切安好。'}
              </div>
            </div>
            <div className="aisp-ov-date">{new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10)}</div>

            {unread > 0 && (
              <button type="button" className="aisp-ov-block" onClick={() => setMode('notifications')}>
                <div className="aisp-ov-block-head"><SvcIcon name="bell" size={15} /> <strong>{unread} 條未讀通知</strong><span className="aisp-ov-chev">›</span></div>
                {notifs.filter(x => x.status !== 'READ').slice(0, 3).map(x => (
                  <div key={x.id} className="aisp-ov-item"><span className="aisp-ov-dot" />{x.title}</div>
                ))}
              </button>
            )}
            {dueTasks.length > 0 && (
              <div className="aisp-ov-block">
                <div className="aisp-ov-block-head"><SvcIcon name="tasks" size={15} /> <strong>今日到期（{dueTasks.length}）</strong></div>
                {dueTasks.slice(0, 3).map(x => (
                  <div key={x.id} className="aisp-ov-item"><span className="aisp-ov-dot" />{x.title}</div>
                ))}
              </div>
            )}
            {/* 2026-09-10 Terrence: 移除 quick chips（🤖 問 AI / 🔔 通知 / 🔍 搜尋）—
                頂部 icon buttons 已經有同樣入口，唔需要重複 */}
          </div>
        )}

        {/* SPEC ai-butler-v2 T3: 通知 tab — 詳細通知 + mark read（中央化通知） */}
        {mode === 'notifications' && (
          <div className="aisp-notif">
            <div className="aisp-notif-toolbar">
              <span>{unread > 0 ? `${unread} 條未讀` : '全部已讀'}</span>
              {unread > 0 && <button type="button" className="aisp-notif-readall" onClick={markAllRead}>全部標為已讀</button>}
            </div>
            {notifs.length === 0 ? (
              <div className="aisp-notif-empty">而家冇通知</div>
            ) : (
              <div className="aisp-notif-list">
                {notifs.map(x => (
                  <button type="button" key={x.id} className={`aisp-notif-item ${x.status !== 'READ' ? 'unread' : ''}`} onClick={() => openNotif(x)}>
                    <span className="aisp-notif-item-dot" />
                    <span className="aisp-notif-item-main">
                      <span className="aisp-notif-item-title">{x.title}</span>
                      {x.body && <span className="aisp-notif-item-body">{x.body}</span>}
                      {x.created_at && <span className="aisp-notif-item-time">{new Date(x.created_at).toLocaleString('zh-HK', { hour12: false, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>}
                    </span>
                    {x.status !== 'READ' && <span className="aisp-notif-item-mark">標為已讀</span>}
                    {notifTarget(x) && <span className="aisp-notif-item-mark">查看 →</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {mode === 'ai' && (
          <div className="aisp-chat">
            {/* Session bar */}
            <div className="aisp-session-bar">
              <button type="button" className={`aisp-session-chip ${!sessionId ? 'active' : ''}`} onClick={createNewSession}>
                <SvcIcon name="plus" /> {t('ai.newChat', { defaultValue: '新對話' })}
              </button>
              {sessionList.slice(0, 8).map(s => (
                <button
                  key={s.session_id}
                  type="button"
                  className={`aisp-session-chip ${sessionId === s.session_id ? 'active' : ''}`}
                  onClick={() => switchSession(s.session_id)}
                  title={s.title}
                >
                  {s.title || t('ai.untitledChat', { defaultValue: '未命名對話' })}
                </button>
              ))}
            </div>

            {/* Messages */}
            <div className="aisp-msg-area" ref={scrollRef}>
              {loadingSession && <div className="aisp-empty">{t('ai.loadingChat', { defaultValue: '載入對話…' })}</div>}
              {emptyChat && (
                <>
                  <div className="aisp-label">{t('ai.aiCanHelp', { defaultValue: 'AI 可以幫你' })}</div>
                  {CAPABILITIES.map(c => (
                    <div key={c.title} className="aisp-capability">
                      <span className="icn"><c.icon /></span>
                      <div><strong>{c.title}</strong><span>{c.desc}</span></div>
                    </div>
                  ))}
                  <div className="aisp-label" style={{ marginTop: 16 }}>{t('ai.quickCommands', { defaultValue: '快速指令' })}</div>
                  <div className="aisp-chip-row">
                    {QUICK_CHIPS.map(chip => (
                      <button key={chip} type="button" className="aisp-chip" onClick={() => setInput(chip)}>
                        <SvcIcon name="sparkles" />{chip}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {messages.map((m) => {
                if (m.role === 'user') {
                  return (
                    <div key={m.id} className="cb-msg-user">
                      <div className="cb-msg-user-bubble">{m.content}</div>
                    </div>
                  );
                }
                return (
                  <div key={m.id} className="cb-msg-ai-row">
                    <div className="cb-msg-ai-body ai-card">
                      {/* v6.88: 對話者名 — Penguin AI（唔用框，用 meta 標示） */}
                      <div className="cb-msg-ai-meta">
                        <span className="cb-msg-time">Penguin AI</span>
                      </div>
                      <div className="msg-ai-content cb-msg-ai-content">
                        <MarkdownMessage content={m.content} />
                      </div>
                      {m.citations && m.citations.length > 0 && (
                        <div className="cb-citation-wrap">
                          <div className="cb-citation-chip">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                            </svg>
                            Source: {m.citations.length} record{m.citations.length > 1 ? 's' : ''}
                          </div>
                        </div>
                      )}
                      {m.followups && m.followups.length > 0 && (
                        <FollowUpChips suggestions={m.followups} onSelect={q => sendMessage(q)} />
                      )}
                    </div>
                  </div>
                );
              })}
              {isStreaming && streamingContent && (
                <div className="cb-msg-ai-row">
                  <div className="cb-msg-ai-body ai-card is-thinking">
                    <div className="msg-ai-content cb-msg-ai-content">
                      <MarkdownMessage content={streamingContent} streaming />
                    </div>
                  </div>
                </div>
              )}
              {isLoading && !streamingContent && (
                <div className="aisp-thinking"><span className="aisp-dot" /><span className="aisp-dot" /><span className="aisp-dot" /></div>
              )}
              {error && <div className="aisp-error">{error}</div>}
            </div>

            {/* Composer（design 嘅 input row，置底）
                2026-09-10 Terrence: 3 個掣跟 main style —
                  1 = 相機（普通影相，唔係名片）
                  2 = 附件（原本係語音 mic）
                  3 = 發送掣移去輸入框「外」，橢圓形 */}
            <div className="aisp-composer">
              <div className="aisp-input-row">
                <input
                  className="aisp-input"
                  placeholder={t('ai.askAnything', { defaultValue: '問 AI 秘書任何事…' })}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') sendMessage(); }}
                />
                {/* 2026-09-10 Terrence: A = 相機影相，B = 相簿揀相 —— 兩個都上傳俾 AI 分析
                    （Qwen3-VL 描述 + OCR → 放入輸入框，用戶可加問題再送） */}
                <input ref={camInputRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }}
                  onChange={e => { const f = e.target.files?.[0]; if (f) void uploadImage(f); e.target.value = ''; }} />
                <input ref={galInputRef} type="file" accept="image/*" style={{ display: 'none' }}
                  onChange={e => { const f = e.target.files?.[0]; if (f) void uploadImage(f); e.target.value = ''; }} />
                <button type="button" className="aisp-icon-btn" disabled={visionBusy} onClick={() => camInputRef.current?.click()} aria-label={t('ai.takePhoto', { defaultValue: '影相' })} title={t('ai.takePhoto', { defaultValue: '影相' })}>
                  <SvcIcon name="camera" size={18} />
                </button>
                <button type="button" className="aisp-icon-btn" disabled={visionBusy} onClick={() => galInputRef.current?.click()} aria-label={t('ai.pickImage', { defaultValue: '相簿／附件' })} title={t('ai.pickImage', { defaultValue: '相簿／附件' })}>
                  <SvcIcon name="attachment" size={18} />
                </button>
              </div>
              <button type="button" className="aisp-send-btn" onClick={() => sendMessage()} disabled={isLoading || isStreaming || !input.trim()} aria-label={t('ai.send', { defaultValue: '送出' })}>
                <SvcIcon name="arrow-up" size={18} />
              </button>
            </div>
          </div>
        )}

        {mode === 'search' && (
          <div className="aisp-search-col">
            <div className="aisp-input-row">
              <SvcIcon name="search" />
              <input
                className="aisp-input"
                placeholder={t('ai.searchPlaceholder', { defaultValue: '搜尋聯絡人、公司、專案、任務…' })}
                value={query}
                onChange={e => setQuery(e.target.value)}
              />
            </div>
            <div className="aisp-filters">
              {SEARCH_FILTERS.map(f => (
                <button
                  key={f.key || 'all'}
                  type="button"
                  className={`aisp-filter-chip ${searchType === f.key ? 'active' : ''}`}
                  onClick={() => setSearchType(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="aisp-body">
              {searching && results.length === 0 && <div className="aisp-empty">{t('ai.searching', { defaultValue: '搜尋中…' })}</div>}
              {!searching && query.trim().length >= 2 && results.length === 0 && <div className="aisp-empty">{t('ai.noResults', { defaultValue: '冇搜尋到相關結果' })}</div>}
              {results.map(r => (
                <button key={r.type + r.id} type="button" className="aisp-result-row" onClick={() => goResult(r)}>
                  <span className="aisp-result-icon">{r.icon}</span>
                  <span className="aisp-result-text">
                    <strong>{r.title}</strong>
                    {r.subtitle && <small>{r.subtitle}</small>}
                  </span>
                  <span className="aisp-result-type">{r.type}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {/* AI action draft（add contact/task 等）→ confirm / reject — 同 desktop 一致（v2 batch） */}
      <ActionPreviewModal
        isOpen={actionQueue.length > 0}
        onClose={() => setActionQueue([])}
        previews={actionQueue}
        onConfirmAll={async (actionIds: string[]) => {
          try {
            await apiClient.post('/api/v1/ai/actions/batch-confirm', { action_ids: actionIds })
          } catch { /* backend 會經 AI 回覆講結果 */ }
          setActionQueue([])
        }}
        onReject={async (actionId: string) => {
          try {
            await apiClient.post(`/api/v1/ai/actions/${actionId}/reject`)
          } catch { /* ignore */ }
          setActionQueue(prev => prev.filter(a => a.action_id !== actionId))
        }}
      />
    </div>,
    document.body
  );
}
