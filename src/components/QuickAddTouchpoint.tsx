import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { apiClient } from '../lib/api';
import BottomSheet from './BottomSheet';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const TYPES = ['meeting', 'call', 'email', 'demo', 'follow-up', 'quote', 'other'];

interface ContactRef { id: string; name: string }

export default function QuickAddTouchpoint({ open, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [type, setType] = useState('meeting');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [contacts, setContacts] = useState<ContactRef[]>([]);
  const [search, setSearch] = useState('');
  const [results, setResults] = useState<ContactRef[]>([]);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const searchRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!search.trim()) { setResults([]); return; }
    clearTimeout(searchRef.current);
    searchRef.current = setTimeout(async () => {
      try {
        const res = await apiClient.get<{ items: ContactRef[]; total: number }>(
          `/api/v1/crm/contacts?search=${encodeURIComponent(search)}&limit=10`
        );
        const existing = new Set(contacts.map(c => c.id));
        setResults((res.items || []).filter(c => !existing.has(c.id)));
      } catch { setResults([]); }
    }, 250);
    return () => clearTimeout(searchRef.current);
  }, [search, contacts]);

  const addContact = (c: ContactRef) => {
    setContacts(prev => [...prev, c]);
    setSearch('');
    setResults([]);
  };

  const removeContact = (id: string) => {
    setContacts(prev => prev.filter(c => c.id !== id));
  };

  const handleSubmit = async () => {
    if (!title.trim()) return;
    setSaving(true);
    try {
      await apiClient.post('/api/v1/crm/touchpoints', {
        type, title: title.trim(),
        description: description.trim() || undefined,
        contact_ids: contacts.map(c => c.id),
      });
      setSaving(false);
      setDone(true);
      setTimeout(() => {
        setDone(false);
        setTitle(''); setDescription(''); setType('meeting');
        setContacts([]); setSearch('');
        onClose(); onCreated();
      }, 1200);
    } catch {
      setSaving(false);
    }
  };

  const btnClass = 'quick-submit' +
    (done ? ' quick-submit--done' : saving ? ' quick-submit--saving' : '');

  return (
    <BottomSheet open={open} onClose={onClose} title={t('touchpoint.new')}>
      <div className="quick-field">
        <label>{t('touchpoint.type')}</label>
        <select value={type} onChange={e => setType(e.target.value)}>
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="quick-field">
        <label>{t('touchpoint.title')} *</label>
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder={t('touchpoint.placeholder')} />
      </div>
      <div className="quick-field pos-relative">
        <label>{t('touchpoint.participants')}</label>
        <div className="tp-chips">
          {contacts.map(c => (
            <span key={c.id} className="tp-chip">{c.name}<button className="tp-chip-x" onClick={() => removeContact(c.id)}>✕</button></span>
          ))}
          <input value={search} onChange={e => setSearch(e.target.value)}
            onFocus={() => setFocused(true)} onBlur={() => setTimeout(() => setFocused(false), 200)}
            placeholder={t('touchpoint.searchPlaceholder')} style={{ flex: 1, minWidth: 120, border: 'none', outline: 'none', fontSize: 13, padding: '4px 0', background: 'transparent' }} />
        </div>
        {focused && results.length > 0 && (
          <div className="tp-dropdown">
            {results.map(c => (
              <div key={c.id} className="tp-dropdown-item" onMouseDown={() => addContact(c)}>
                <span className="avatar-xs">{c.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}</span>
                {c.name}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="quick-field">
        <label>{t('touchpoint.notes')}</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder={t('touchpoint.notesPlaceholder')} rows={3} />
      </div>
      <button className={btnClass} onClick={handleSubmit} disabled={saving || !title.trim()}>
        {done ? '✓ Saved' : saving ? 'Saving…' : 'Create Touchpoint'}
      </button>
    </BottomSheet>
  );
}
