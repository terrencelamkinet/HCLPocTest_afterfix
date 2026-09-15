import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { apiClient } from '../lib/api';
import { Lightbulb } from 'lucide-react'
import SvcIcon from '../components/SvcIcon';

// ── Types ──
interface WeatherData {
  temp: number;
  condition: string;
  icon: string | number;
  icon_emoji?: string;
  desc?: string;
}

interface ScheduleEvent {
  id: string;
  title: string;
  time: string;
  location?: string;
}

interface TaskItem {
  id: string;
  title: string;
  priority: string;
  status: string;
  due_date: string | null;
}

interface AiTip {
  text: string;
}

interface BriefingData {
  weather: WeatherData;
  schedule: ScheduleEvent[];
  tasks: TaskItem[];
  aiTip: AiTip;
  content?: string;   // LLM-generated briefing (AI-app pipeline)
  slot?: string;
  generatedAt?: string;
}

// ── Props ──
interface Props {
  className?: string;
  style?: React.CSSProperties;
}

// ── Mock fallback data ──
const mockBriefing: BriefingData = {
  weather: { temp: 28, condition: 'Partly Cloudy', icon: 51, icon_emoji: '🌤️', desc: '部分時間有陽光' },
  schedule: [
    { id: 'mock-ev-1', title: 'Team standup', time: '09:30', location: 'Meeting Room A' },
    { id: 'mock-ev-2', title: 'Client review call', time: '14:00' },
    { id: 'mock-ev-3', title: 'Q3 planning', time: '16:00', location: 'Boardroom' },
  ],
  tasks: [],
  aiTip: { text: 'Review your pending proposals — 2 deals are in negotiation stage and could benefit from a follow-up this morning.' },
};

const mockTasks: TaskItem[] = [
  { id: 'demo-t-1', title: 'Follow up with TechCorp proposal', priority: 'P0', status: 'pending', due_date: new Date().toISOString() },
  { id: 'demo-t-2', title: 'Review Q3 pipeline report', priority: 'P1', status: 'in_progress', due_date: new Date().toISOString() },
  { id: 'demo-t-3', title: 'Prepare client presentation', priority: 'P1', status: 'pending', due_date: new Date().toISOString() },
];

// ── Helpers ──
const slotLabel = (slot: string): string => {
  const map: Record<string, string> = {
    morning: '早安', noon: '午安', evening: '晚安', night: '深夜',
  };
  return map[slot] || slot;
};

const formatLastUpdated = (date: Date): string => {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHrs = Math.floor(diffMin / 60);
  return `${diffHrs}h ago`;
};

/** Extract HH:MM from 'YYYY-MM-DD HH:MM' (API, HKT) or passthrough bare 'HH:MM' (mock). */
const fmtEventTime = (time: string): string =>
  time.length >= 16 ? time.slice(11, 16) : time;

// ── Skeleton ──
function BriefingSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      {/* header */}
      <div className="flex items-center justify-between">
        <div className="h-5 bg-[var(--color-surface-offset)] rounded w-32" />
        <div className="h-8 w-8 bg-[var(--color-surface-offset)] rounded-full" />
      </div>
      {/* 3 pulsing rows */}
      <div className="space-y-3">
        <div className="h-14 bg-[var(--color-surface-offset)] rounded-lg" />
        <div className="h-14 bg-[var(--color-surface-offset)] rounded-lg" />
        <div className="h-14 bg-[var(--color-surface-offset)] rounded-lg" />
      </div>
      <div className="h-3 bg-[var(--color-surface-offset)] rounded w-24" />
    </div>
  );
}

// ── Component ──
export default function DailyBriefingCard({ className = '', style }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const fetchBriefing = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<{
        weather: any;
        schedule: ScheduleEvent[];
        tasks: TaskItem[];
        ai_tip: string;
        content?: string;
        slot?: string;
        generated_at?: string;
      }>('/api/v1/ai/briefing');

      setData({
        weather: res?.weather || mockBriefing.weather,
        schedule: (res?.schedule || []).slice(0, 5),
        tasks: (res?.tasks || []).slice(0, 5) as TaskItem[],
        aiTip: { text: res?.ai_tip || mockBriefing.aiTip.text },
        content: res?.content || '',
        slot: res?.slot || '',
        generatedAt: res?.generated_at || '',
      });
      setLastUpdated(new Date());
    } catch {
      // Fallback to mock data on any error
      setData({
        weather: mockBriefing.weather,
        schedule: mockBriefing.schedule,
        tasks: mockTasks.filter(t => t.priority === 'P0' || t.priority === 'P1'),
        aiTip: mockBriefing.aiTip,
      });
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBriefing();
  }, [fetchBriefing]);

  // ── Error state ──
  if (error && !data) {
    return (
      <div className={className} style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-divider)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-sm)',
        padding: '18px 20px',
        ...style,
      }}>
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12 }}>{error}</p>
          <button
            onClick={fetchBriefing}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '8px 16px', borderRadius: 'var(--radius-md)',
              background: 'var(--color-primary)', color: '#fff',
              border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            <SvcIcon name="refresh-cw" size={14} />
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Loading state ──
  if (loading && !data) {
    return (
      <div className={className} style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-divider)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-sm)',
        padding: '18px 20px',
        ...style,
      }}>
        <BriefingSkeleton />
      </div>
    );
  }

  // ── Render ──
  return (
    <div className={className} style={{
      background: 'var(--color-surface)',
      border: '1px solid var(--color-divider)',
      borderRadius: 'var(--radius-lg)',
      boxShadow: 'var(--shadow-sm)',
      padding: '18px 20px',
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      ...style,
    }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SvcIcon name="sparkles" size={16} style={{ color: 'var(--color-purple)' }} />
          <h3 style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.01em' }}>
            {t('pages.briefing.title')}
          </h3>
        </div>
        <button
          onClick={fetchBriefing}
          disabled={loading}
          title={t('pages.briefing.refresh')}
          style={{
            width: 32, height: 32, display: 'flex', alignItems: 'center',
            justifyContent: 'center', borderRadius: 'var(--radius-md)',
            color: 'var(--color-text-muted)', cursor: 'pointer',
            background: 'none', border: 'none', transition: 'background 150ms',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-surface-offset)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'none')}
        >
          <SvcIcon name="refresh-cw" size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
        </button>
      </div>

      {/* ── LLM-generated briefing (AI-app pipeline) ── */}
      {data!.content && (
        <div style={{
          background: 'color-mix(in oklch, var(--color-purple) 8%, var(--color-surface))',
          border: '1px solid color-mix(in oklch, var(--color-purple) 25%, transparent)',
          borderRadius: 'var(--radius-md)',
          padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--color-purple)', marginBottom: 6, letterSpacing: 0.3 }}>
            🤖 AI 簡報{data!.slot ? ` · ${slotLabel(data!.slot)}` : ''}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--color-text)', lineHeight: 1.65, whiteSpace: 'pre-wrap' }}>
            {data!.content}
          </div>
        </div>
      )}

      {/* ── Sections ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

        {/* Weather */}
        <SectionRow
          icon={
            data!.weather?.icon_emoji ? (
              <span className="dbc-weather-emoji" style={{ fontSize: 15, lineHeight: 1 }}>{data!.weather.icon_emoji}</span>
            ) : (
              <SvcIcon name="sun" size={15} style={{ color: 'var(--color-warning)' }} />
            )
          }
          label={t('pages.briefing.weather')}
          onClick={() => {/* navigate to weather page */}}
        >
          <span style={{ fontSize: 15, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
            {data!.weather.temp}°
          </span>
          {data!.weather?.desc && (
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--color-text-muted)' }}>
              {data!.weather.desc}
            </span>
          )}
          <span style={{ fontSize: 12.5, color: 'var(--color-text-muted)' }}>
            {data!.weather.condition}
          </span>
        </SectionRow>

        {/* Schedule */}
        <SectionRow
          icon={<SvcIcon name="calendar" size={15} style={{ color: 'var(--color-blue)' }} />}
          label={t('pages.briefing.schedule')}
          onClick={() => {/* navigate to calendar */}}
        >
          {data!.schedule.length === 0 ? (
            <span style={{ fontSize: 12.5, color: 'var(--color-text-faint)' }}>{t('pages.briefing.noEvents')}</span>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              {data!.schedule.slice(0, 3).map(ev => (
                <div key={ev.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
                  <span style={{ fontWeight: 600, color: 'var(--color-text-muted)', whiteSpace: 'nowrap', minWidth: 40 }}>
                    {fmtEventTime(ev.time)}
                  </span>
                  <span style={{ color: 'var(--color-text)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {ev.title}
                  </span>
                  {ev.location && (
                    <span style={{ color: 'var(--color-text-faint)', fontSize: 11.5, marginLeft: 'auto' }}>
                      {ev.location}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </SectionRow>

        {/* Tasks */}
        <SectionRow
          icon={<SvcIcon name="check-square" size={15} style={{ color: 'var(--color-notification)' }} />}
          label={t('pages.briefing.tasks')}
          onClick={() => {/* navigate to tasks */}}
        >
          {data!.tasks.length === 0 ? (
            <span style={{ fontSize: 12.5, color: 'var(--color-text-faint)' }}>{t('pages.briefing.noTasks')}</span>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              {data!.tasks.slice(0, 5).map(t => (
                <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
                  <span style={{
                    display: 'inline-flex', padding: '1px 6px', borderRadius: 'var(--radius-sm)',
                    fontSize: 10, fontWeight: 700, lineHeight: '16px',
                    background: t.priority === 'P0'
                      ? 'color-mix(in oklch, var(--color-notification) 18%, var(--color-surface))'
                      : 'color-mix(in oklch, var(--color-warning) 18%, var(--color-surface))',
                    color: t.priority === 'P0' ? 'var(--color-notification)' : 'var(--color-warning)',
                  }}>
                    {t.priority}
                  </span>
                  <span style={{ color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {t.title}
                  </span>
                </div>
              ))}
            </div>
          )}
        </SectionRow>

        {/* AI Tip */}
        <SectionRow
          icon={<Lightbulb size={15} style={{ color: 'var(--color-purple)' }} />}
          label={t('pages.briefing.aiTip')}
          onClick={() => {/* navigate to AI insights */}}
        >
          <span style={{ fontSize: 12.5, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
            {data!.aiTip.text}
          </span>
        </SectionRow>
      </div>

      {/* ── Footer: last updated ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 5,
        fontSize: 11, color: 'var(--color-text-faint)',
        borderTop: '1px solid var(--color-divider)',
        paddingTop: 10, marginTop: 2,
      }}>
        <SvcIcon name="clock" size={11} />
        <span>{t('pages.briefing.updated', { time: formatLastUpdated(lastUpdated) })}</span>
      </div>

      {/* ── Keyframes for spin animation ── */}
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

// ── Section Row Sub-component ──
function SectionRow({
  icon,
  label,
  children,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') onClick(); } : undefined}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        padding: '10px 12px',
        borderRadius: 'var(--radius-md)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 150ms',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-surface-offset)'; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      <div style={{
        width: 30, height: 30, borderRadius: 'var(--radius-sm)',
        background: 'var(--color-surface-offset)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, marginTop: 1,
      }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {label}
        </div>
        {children}
      </div>
    </div>
  );
}
