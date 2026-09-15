import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';
import { apiClient } from '../lib/api';
import FollowUpChips from '../components/ai/chat/core/FollowUpChips';
import MarkdownMessage from '../components/MarkdownRenderer';
import { useTranslation } from 'react-i18next';

/**
 * Fullscreen AI chat page (v6.76) — 由 AI&Search panel 全螢幕按鈕（AI tab）進入。
 * 同一套 session / streaming / citations / follow-ups 邏輯，全螢幕體驗。
 */

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
function assistantMessage(content: string): ChatMessage { return { id: nextId(), role: 'assistant', content, timestamp: Date.now() }; }

const GREETING = "Hi! I'm Penguin AI. How can I help you today?";
const QUICK_CHIPS = ['總結今日待辦', '幫我起草跟進 email', '分析專案風險'];

export default function AiPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionList, setSessionList] = useState<SessionItem[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

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
      // v6.90: 每次入 fullscreen AI 頁都係新對話 — 唔好自動 switch 去舊
      // session（同 panel 一致）。之前自動 load active/first session →
      // AI 帶住舊 context 答非所問。舊對話喺 session chips 自己揀。
      setSessionId(null);
      setMessages([assistantMessage(GREETING)]);
    } catch {
      setMessages([assistantMessage(GREETING)]);
    } finally {
      setLoadingSession(false);
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const createNewSession = () => {
    abortRef.current?.abort();
    setSessionId(null);
    setMessages([]);
    setError(null);
  };

  /* ── Streaming ── */
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
      if (e.name !== 'AbortError') setError(e?.message || '請求失敗，請再試');
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

  /* ── Auto-scroll ── */
  useEffect(() => {
    const el = scrollRef.current;
    if (el) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }, [messages, isStreaming, streamingContent, isLoading]);

  const emptyChat = messages.length === 0 && !loadingSession && !isStreaming;

  return (
    <div className="aipage-page">
      <header className="aipage-head">
        <button type="button" className="aipage-back" onClick={() => navigate(-1)} aria-label={t('common.back', { defaultValue: '返回' })}>
          <SvcIcon name="arrow-left" />
        </button>
        <h3>{t('ai.aiButler', { defaultValue: 'AI 管家秘書' })}</h3>
      </header>

      <div className="aipage-chat">
        {/* Session bar */}
        <div className="aisp-session-bar">
          <button type="button" className={`aisp-session-chip ${!sessionId ? 'active' : ''}`} onClick={createNewSession}>
            <SvcIcon name="plus" />{t('chat.newChat', { defaultValue: '新對話' })}
          </button>
          {sessionList.slice(0, 10).map(s => (
            <button
              key={s.session_id}
              type="button"
              className={`aisp-session-chip ${sessionId === s.session_id ? 'active' : ''}`}
              onClick={() => switchSession(s.session_id)}
              title={s.title}
            >
              {s.title || '未命名對話'}
            </button>
          ))}
        </div>

        {/* Messages */}
        <div className="aisp-msg-area aipage-msg-area" ref={scrollRef}>
          {loadingSession && <div className="aisp-empty">{t('ai.loadingChat', { defaultValue: '載入對話…' })}</div>}
          {emptyChat && (
            <>
              <div className="aisp-label" style={{ marginTop: 8 }}>{t('ai.quickCommands', { defaultValue: '快速指令' })}</div>
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

        {/* Composer */}
        <div className="aisp-input-row">
          <input
            className="aisp-input"
            placeholder={t('ai.askAnything', { defaultValue: '問 AI 秘書任何事…' })}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') sendMessage(); }}
          />
          <button type="button" className="aisp-icon-btn mic" onClick={() => setInput(prev => prev + '（語音輸入即將推出）')} aria-label={t('ai.voiceInput', { defaultValue: '語音輸入' })}>
            <SvcIcon name="mic" />
          </button>
          <button type="button" className="aisp-icon-btn send" onClick={() => sendMessage()} disabled={isLoading || isStreaming || !input.trim()} aria-label={t('ai.send', { defaultValue: '送出' })}>
            <SvcIcon name="arrow-up" />
          </button>
        </div>
      </div>
    </div>
  );
}
