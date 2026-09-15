import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../../../components/SvcIcon';
import type { CalendarEventFormatted } from './types';
import { TYPE_COLORS, SOURCE_LABELS } from './types';
import { apiClient } from '../../../lib/api';
import { useEscapeKey } from '../../../lib/useEscapeKey';

interface EventReviewModalProps {
  event?: CalendarEventFormatted | null;
  initialDate?: Date;
  onClose: () => void;
  onSaved: () => void;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function toTimeInput(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDateLong(d: Date): string {
  return d.toLocaleDateString('en-US', { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
}

export default function EventReviewModal({ event, initialDate, onClose, onSaved }: EventReviewModalProps) {
  const { i18n } = useTranslation()
  const locale = i18n.language || 'en'
  // Real calendar events come from project_calendar_events (id: `cal-<uuid>`).
  // Touchpoints (tp-*) and tasks (task-*) are read-only here.
  // No event = create mode (Add button / double-click).
  const isCreate = !event;
  const isEditable = isCreate || event!.id.startsWith('cal-');
  const rawId = isEditable ? (isCreate ? null : event!.id.replace(/^cal-/, '')) : event!.id;

  // Create-mode default date: initialDate if provided, else today, default 09:00.
  const createDefault = initialDate || new Date();

  useEscapeKey(onClose);

  const [editing, setEditing] = useState(isCreate);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [title, setTitle] = useState(isCreate ? '' : event!.title);
  const [eventType, setEventType] = useState(isCreate ? 'meeting' : (event!.eventType || 'meeting'));
  const [startDate, setStartDate] = useState(isCreate ? toDateInput(createDefault) : toDateInput(event!.start));
  const [startTime, setStartTime] = useState(isCreate ? '09:00' : toTimeInput(event!.start));
  const [allDay, setAllDay] = useState(isCreate ? false : event!.allDay);
  const [location, setLocation] = useState(isCreate ? '' : (event!.location || ''));
  const [description, setDescription] = useState(isCreate ? '' : (event!.description || ''));

  const sourceLabel = isCreate
    ? (SOURCE_LABELS.manual || null)
    : (event!.source && SOURCE_LABELS[event!.source] ? SOURCE_LABELS[event!.source] : null);
  const badgeColor = isCreate
    ? '#00693E'
    : event!.source === 'google_oauth' ? '#4285F4'
    : event!.source === 'ics' ? '#34A853'
    : event!.source === 'outlook' ? '#0078D4'
    : (event!.eventType && TYPE_COLORS[event!.eventType]) || '#6B7280';

  const handleSave = async () => {
    if (!title.trim()) {
      setError('Title is required');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const start = new Date(`${startDate}T${allDay ? '00:00' : (startTime || '00:00')}`);
      const end = new Date(start.getTime() + 60 * 60 * 1000);
      const body = {
        title: title.trim(),
        description: description.trim() || null,
        event_type: eventType,
        start: start.toISOString(),
        end: end.toISOString(),
        is_all_day: allDay,
        color: event?.color || undefined,
        location: location.trim() || null,
      };
      if (isCreate) {
        await apiClient.post('/api/v1/crm/calendar-events', body);
      } else {
        await apiClient.patch(`/api/v1/crm/calendar-events/${rawId}`, body);
      }
      setEditing(false);
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Failed to save event');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiClient.delete(`/api/v1/crm/calendar-events/${rawId}`);
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Failed to delete event');
      setSaving(false);
    }
  };

  return (
    <div className="er-overlay" onClick={onClose}>
      <div className="er-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {/* Header */}
        <div className="er-header">
          <h3>{editing ? (isCreate ? 'New Event' : 'Edit Event') : 'Event Review'}</h3>
          <button className="er-close" onClick={onClose} aria-label="Close">
            <SvcIcon name="x" className="w-4 h-4" />
          </button>
        </div>

        {editing ? (
          /* ── Edit mode ── */
          <div className="er-body">
            <label className="er-field">
              <span>Title</span>
              <input
                className="er-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Event title"
                autoFocus
              />
            </label>

            <label className="er-field">
              <span>Type</span>
              <select className="er-input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
                <option value="milestone">Milestone</option>
                <option value="task">Task</option>
                <option value="meeting">Meeting</option>
                <option value="reminder">Reminder</option>
              </select>
            </label>

            <div className="er-row">
              <label className="er-field">
                <span>Date</span>
                <input
                  type="date"
                  className="er-input"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </label>

              <label className="er-field">
                <span>Time</span>
                <input
                  type="time"
                  className="er-input"
                  value={startTime}
                  disabled={allDay}
                  onChange={(e) => setStartTime(e.target.value)}
                />
              </label>
            </div>

            <label className="er-check">
              <input
                type="checkbox"
                checked={allDay}
                onChange={(e) => setAllDay(e.target.checked)}
              />
              <span>All day</span>
            </label>

            <label className="er-field">
              <span>Location</span>
              <input
                className="er-input"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Location (optional)"
              />
            </label>

            <label className="er-field">
              <span>Description</span>
              <textarea
                className="er-input er-textarea"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Notes (optional)"
                rows={3}
              />
            </label>

            {error && <div className="er-error">{error}</div>}

            <div className="er-actions">
              <button className="er-btn ghost" onClick={() => { setEditing(false); setError(null); }} disabled={saving}>
                Cancel
              </button>
              <button className="er-btn primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        ) : (
          /* ── Review mode ── */
          <div className="er-body">
            <div className="er-title-row">
              <h2 className="er-title">{event!.title}</h2>
              <span className="er-badge" style={{ backgroundColor: badgeColor }}>
                {sourceLabel || event!.eventType || 'Event'}
              </span>
            </div>

            <div className="er-meta">
              <div className="er-meta-item">
                <SvcIcon name="calendar-days" className="w-4 h-4" />
                <span>
                  {formatDateLong(event!.start)}
                  {!event!.allDay && (
                    <> · {event!.start.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
                      {event!.end && ` – ${event!.end.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}`}</>
                  )}
                </span>
              </div>
              {event!.location && (
                <div className="er-meta-item">
                  <SvcIcon name="map-pin" className="w-4 h-4" />
                  <span>{event!.location}</span>
                </div>
              )}
              {event!.projectName && (
                <div className="er-meta-item">
                  <SvcIcon name="clock" className="w-4 h-4" />
                  <span>{event!.projectName}</span>
                </div>
              )}
            </div>

            {event!.description && (
              <div className="er-desc">{event!.description}</div>
            )}

            {!isEditable && (
              <div className="er-note">
                This event comes from a {event!.id.startsWith('tp-') ? 'touchpoint' : 'task'}.
                Edit it in the corresponding module.
              </div>
            )}

            {error && <div className="er-error">{error}</div>}

            {confirmDelete ? (
              <div className="er-actions">
                <button className="er-btn ghost" onClick={() => setConfirmDelete(false)} disabled={saving}>
                  Cancel
                </button>
                <button className="er-btn danger" onClick={handleDelete} disabled={saving}>
                  {saving ? 'Deleting…' : 'Confirm Delete'}
                </button>
              </div>
            ) : (
              <div className="er-actions">
                <button className="er-btn ghost" onClick={onClose}>
                  Close
                </button>
                {isEditable && (
                  <>
                    <button className="er-btn ghost danger-ghost" onClick={() => setConfirmDelete(true)} disabled={saving}>
                      <SvcIcon name="trash-2" className="w-3.5 h-3.5" />
                      Delete
                    </button>
                    <button className="er-btn primary" onClick={() => setEditing(true)}>
                      <SvcIcon name="pencil" className="w-3.5 h-3.5" />
                      Edit Event
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
