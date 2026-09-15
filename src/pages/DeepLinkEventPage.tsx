import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '../lib/api';
import { useTranslation } from 'react-i18next';

interface CalendarEvent {
  id: string;
  title: string;
  description?: string | null;
  start: string;
  end: string;
  location?: string | null;
  event_type?: string | null;
}

/**
 * Deep-link landing for IM-push briefing links:
 * - /l/m/{id}   → meeting prep card (會議準備卡)
 * - /l/note/{id} → voice-note follow-up (開咗會未留底 → 一鍵留底)
 *
 * Shows the calendar event + a one-tap touchpoint logger (pre-filled
 * with the event title). No AI-meeting-brief table dependency — the
 * prep card degrades gracefully to event info + quick log.
 */
export default function DeepLinkEventPage({ mode }: { mode: 'prep' | 'note' }) {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // touchpoint form state
  const [type, setType] = useState('meeting');
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    apiClient
      .get<CalendarEvent>(`/api/v1/crm/calendar-events/${id}`)
      .then((evt) => {
        setEvent(evt);
        setTitle(evt.title || '');
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [id]);

  const fmtTime = (iso: string) => {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '--:--';
    return d.toLocaleString('zh-HK', {
      month: 'numeric', day: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  };

  const handleLog = async () => {
    if (!title.trim()) return;
    setSaving(true);
    setError('');
    try {
      await apiClient.post('/api/v1/crm/touchpoints', {
        type, title: title.trim(),
        description: notes.trim() || undefined,
        date: event ? new Date(event.start).toISOString() : undefined,
      });
      setDone(true);
      setTimeout(() => navigate('/touchpoints', { replace: true }), 1200);
    } catch {
      setError('儲存失敗，請稍後再試');
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#64748b', fontSize: 14 }}>{t('common.loading', { defaultValue: '載入中…' })}</div>
    );
  }

  if (notFound || !event) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>{t('deeplink.eventNotFound', { defaultValue: '找不到這個會議' })}</div>
        <div style={{ color: '#64748b', fontSize: 13, marginBottom: 20 }}>{t('deeplink.eventMissing', { defaultValue: '活動可能已刪除，或你冇權限查看。' })}</div>
        <button className="quick-submit" onClick={() => navigate('/dashboard', { replace: true })}>{t('deeplink.backToDashboard', { defaultValue: '返回 Dashboard' })}</button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 520, margin: '0 auto', padding: '24px 16px 60px' }}>
      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>
          {mode === 'prep' ? '📎 AI 會議準備卡' : '🎙 會議留底'}
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, lineHeight: 1.3 }}>
          {event.title || 'Untitled Event'}
        </h1>
        <div style={{ fontSize: 14, color: '#475569', marginTop: 8 }}>
          🕐 {fmtTime(event.start)} — {fmtTime(event.end)}
        </div>
        {event.location && (
          <div style={{ fontSize: 14, color: '#475569', marginTop: 4 }}>
            📍 {event.location}
          </div>
        )}
      </div>

      {mode === 'note' && (
        <div style={{
          background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 12,
          padding: '12px 14px', fontSize: 13, color: '#9a3412', marginBottom: 16,
        }}>{t('deeplink.detectedMeeting', { defaultValue: '偵測到你今日開咗呢個會，但 CRM 未有紀錄。用下面表單 30 秒留底 👇' })}</div>
      )}

      {/* Quick touchpoint logger */}
      <div style={{
        background: '#fff', border: '1px solid #e2e8f0', borderRadius: 14,
        padding: 16, boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
      }}>
        <div className="quick-field">
          <label>{t('common.type', { defaultValue: '類型' })}</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {['meeting', 'call', 'email', 'demo', 'follow-up', 'quote', 'other'].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="quick-field">
          <label>{t('contacts.detail.titleRequired', { defaultValue: '標題 *' })}</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('deeplink.titlePlaceholder', { defaultValue: '會議 / 跟進事項' })} />
        </div>
        <div className="quick-field">
          <label>{t('common.content', { defaultValue: '內容' })}</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t('deeplink.notesPlaceholder', { defaultValue: '記低會議重點、跟進事項…' })}
            rows={3}
          />
        </div>
        {error && <div style={{ color: '#dc2626', fontSize: 13, marginBottom: 8 }}>{error}</div>}
        <button
          className={`quick-submit${done ? ' quick-submit--done' : ''}${saving ? ' quick-submit--saving' : ''}`}
          onClick={handleLog}
          disabled={saving || !title.trim()}
          style={{ width: '100%' }}
        >
          {done ? '✓ 已留底！' : saving ? '儲存中…' : '💾 留底 Touchpoint'}
        </button>
        <button
          onClick={() => navigate('/dashboard', { replace: true })}
          style={{
            width: '100%', marginTop: 8, padding: '10px 0', background: 'none',
            border: 'none', color: '#64748b', fontSize: 13, cursor: 'pointer',
          }}
        >{t('deeplink.backToDashboard', { defaultValue: '返回 Dashboard' })}</button>
      </div>
    </div>
  );
}
