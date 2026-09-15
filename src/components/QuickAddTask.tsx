import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { apiClient } from '../lib/api';
import BottomSheet from './BottomSheet';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const PRIORITIES = ['P0', 'P1', 'P2', 'P3'];

export default function QuickAddTask({ open, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState('P2');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  const handleSubmit = async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      await apiClient.post('/api/v1/crm/tasks', {
        title: title.trim(),
        priority,
        description: description.trim() || undefined,
        status: 'pending',
      });
      setSaving(false);
      setDone(true);
      setTimeout(() => {
        setDone(false);
        setTitle(''); setPriority('P2'); setDescription('');
        onClose(); onCreated();
      }, 1200);
    } catch {
      setSaving(false);
    }
  };

  const btnClass = 'quick-submit' +
    (done ? ' quick-submit--done' : saving ? ' quick-submit--saving' : '');

  return (
    <BottomSheet open={open} onClose={onClose} title={t('quickAdd.task')}>
      <div className="quick-field">
        <label>{t('pages.tasks.taskTitle')} *</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder={t('quickAdd.taskPlaceholder')} />
      </div>
      <div className="quick-field">
        <label>{t('pages.tasks.priority')}</label>
        <select value={priority} onChange={e => setPriority(e.target.value)}>
          {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      <div className="quick-field">
        <label>{t('pages.tasks.description')}</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder={t('quickAdd.details')} rows={3} />
      </div>
      <button className={btnClass} onClick={handleSubmit} disabled={saving || !title.trim()}>
        {done ? '✓ Saved' : saving ? 'Saving…' : 'Create Task'}
      </button>
    </BottomSheet>
  );
}
