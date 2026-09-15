import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../components/SvcIcon';
import { useNavigate } from 'react-router-dom';
import { useApi, useSearch, useCreateModal, TableSkeleton, ErrorBox } from '../lib/useApi';
import { apiClient } from '../lib/api';
import EntitySearch from '../modules/shared/EntitySearch';
import useColumnConfig from '../lib/useColumnConfig';
import BottomSheet from '../components/BottomSheet';
import SlideDrawer from '../components/SlideDrawer';
import DetailDrawerContent from '../modules/shared/DetailDrawerContent';
import contactConfig from '../modules/contacts/config';

interface Contact {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  status: string;
  company?: { id: string; name: string } | null;
  created_at: string;
  last_touch?: string | null;
  chinese_name?: string | null;
  nick_name?: string | null;
  contact_type?: string | null;
  grade?: string | null;
  numbers?: string[];
  office_phone?: string | null;
  namecard_path?: string | null;
  job_title?: string | null;
  department?: string | null;
  linkedin_url?: string | null;
  address?: string | null;
  notes?: string | null;
  tags?: string[];
}

interface ContactListResponse {
  items: Contact[];
  total: number;
}

const statusColors: Record<string, string> = {
  Active: 'tag-active',
  Warm: 'tag-warm',
  Cold: 'tag-cold',
  VIP: 'tag-vip',
  Inactive: 'tag-default',
};

const defaultForm = {
  name: '', email: '', phone: '', status: 'Active', company_id: '',
  chinese_name: '', nick_name: '', contact_type: '', grade: '',
  numbers: [] as string[], office_phone: '', job_title: '',
  department: '', linkedin_url: '', address: '', notes: '',
  tags: [] as string[], country_code: '+852',
};

/* T9 (2026-09-07): 電話國碼選單 — 國家名 alphabetical（Terrence: 「以國家名排列 + 國碼」） */
const COUNTRY_CODES: { name: string; code: string }[] = [
  { name: 'Australia', code: '+61' }, { name: 'Austria', code: '+43' },
  { name: 'Bangladesh', code: '+880' }, { name: 'Belgium', code: '+32' },
  { name: 'Brazil', code: '+55' }, { name: 'Cambodia', code: '+855' },
  { name: 'China', code: '+86' }, { name: 'Denmark', code: '+45' },
  { name: 'Finland', code: '+358' }, { name: 'France', code: '+33' },
  { name: 'Germany', code: '+49' }, { name: 'Hong Kong', code: '+852' },
  { name: 'India', code: '+91' }, { name: 'Indonesia', code: '+62' },
  { name: 'Ireland', code: '+353' }, { name: 'Israel', code: '+972' },
  { name: 'Italy', code: '+39' }, { name: 'Japan', code: '+81' },
  { name: 'Macau', code: '+853' }, { name: 'Malaysia', code: '+60' },
  { name: 'Mexico', code: '+52' }, { name: 'Myanmar', code: '+95' },
  { name: 'Netherlands', code: '+31' }, { name: 'New Zealand', code: '+64' },
  { name: 'Norway', code: '+47' }, { name: 'Philippines', code: '+63' },
  { name: 'Poland', code: '+48' }, { name: 'Portugal', code: '+351' },
  { name: 'Russia', code: '+7' }, { name: 'Saudi Arabia', code: '+966' },
  { name: 'Singapore', code: '+65' }, { name: 'South Africa', code: '+27' },
  { name: 'South Korea', code: '+82' }, { name: 'Spain', code: '+34' },
  { name: 'Sweden', code: '+46' }, { name: 'Switzerland', code: '+41' },
  { name: 'Taiwan', code: '+886' }, { name: 'Thailand', code: '+66' },
  { name: 'Turkey', code: '+90' }, { name: 'UAE', code: '+971' },
  { name: 'United Kingdom', code: '+44' }, { name: 'United States', code: '+1' },
  { name: 'Vietnam', code: '+84' },
].sort((a, b) => a.name.localeCompare(b.name));

/* parse "+85200000000" → { code: '+852', local: '91234567' }（冇 match code → 用 caller 提供嘅 default） */
function splitPhone(raw: string | null, defCode: string): { code: string; local: string } {
  const v = (raw || '').replace(/\s+/g, '');
  if (!v) return { code: defCode, local: '' };
  if (v.startsWith('+')) {
    const hit = COUNTRY_CODES.find(c => v.startsWith(c.code));
    if (hit) return { code: hit.code, local: v.slice(hit.code.length) };
  }
  return { code: defCode, local: v }; // 冇 match → 當本地號碼（用 default code）
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return '—';
  }
}

// ---- Shared form fields (stable component — defined outside to avoid remount on every keystroke) ----
interface FormFieldsProps {
  form: typeof defaultForm;
  setForm: React.Dispatch<React.SetStateAction<typeof defaultForm>>;
  inputCls: string;
}

const inputCls = "input-field";

// ---- Shared helper for multi-select checkboxes ----
const CheckboxGroup = ({ label, options, selected, onChange, showCustom, onAddCustom }: {
  label: string; options: string[]; selected: string[]; onChange: (v: string[]) => void;
  showCustom?: boolean; onAddCustom?: (v: string) => void;
}) => {
  const [customVal, setCustomVal] = useState('');
  // 自訂 tag 都要顯示返出嚟（selected 有但 options 冇 → 照 show + checked）
  const all = options.concat(selected.filter(s => !options.includes(s)));
  const addCustom = () => {
    const v = customVal.trim();
    if (!v || !onAddCustom) return;
    onAddCustom(v);
    setCustomVal('');
  };
  return (
    <div>
      <label className="field-label">{label}</label>
      <div className="checkbox-group">
        {all.map(opt => (
          <label key={opt} className="checkbox-label">
            <input type="checkbox" checked={selected.includes(opt)}
              onChange={e => {
                if (e.target.checked) onChange([...selected, opt]);
                else onChange(selected.filter(t => t !== opt));
              }}
              className="checkbox-input" />
            {opt}
          </label>
        ))}
        {showCustom && (
          <span className="checkbox-label checkbox-custom-add">
            <input type="text" value={customVal} placeholder="新增標籤…" maxLength={20}
              onChange={e => setCustomVal(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') addCustom(); }}
              className="checkbox-custom-input" />
            <button type="button" className="checkbox-custom-btn" onClick={addCustom} aria-label="新增標籤">
              <SvcIcon name="plus" className="icon-12" />
            </button>
          </span>
        )}
      </div>
    </div>
  );
};

function ContactFormFields({ form, setForm, inputCls }: FormFieldsProps) {
  const { t } = useTranslation();
  return (
    <div className="grid-2col">
      {/* Name, Chinese Name */}
      <div className="form-field">
        <label className="field-label">{t('common.nameRequired')}</label>
        <input type="text" value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderContactName')} />
      </div>
      <div className="form-field">
        <label className="field-label">{t('common.chineseName')}</label>
        <input type="text" value={form.chinese_name}
          onChange={e => setForm(f => ({ ...f, chinese_name: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderChineseName')} />
      </div>

      {/* Nick Name, Job Title */}
      <div className="form-field">
        <label className="field-label">{t('common.nickName')}</label>
        <input type="text" value={form.nick_name}
          onChange={e => setForm(f => ({ ...f, nick_name: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderNickName')} />
      </div>
      <div className="form-field">
        <label className="field-label">{t('common.jobTitle')}</label>
        <input type="text" value={form.job_title}
          onChange={e => setForm(f => ({ ...f, job_title: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderJobTitle')} />
      </div>

      {/* Department, Contact Type */}
      <div className="form-field">
        <label className="field-label">{t('common.department')}</label>
        <input type="text" value={form.department}
          onChange={e => setForm(f => ({ ...f, department: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderDepartment')} />
      </div>
      <div className="form-field">
        <label className="field-label">{t('common.contactType')}</label>
        <select value={form.contact_type}
          onChange={e => setForm(f => ({ ...f, contact_type: e.target.value }))}
          className={inputCls}>
          <option value="">— {t('common.select')} —</option>
          <option value="Distributor">{t('common.distributor')}</option>
          <option value="Vendor">{t('common.vendor')}</option>
          <option value="Client">{t('common.client')}</option>
        </select>
      </div>

      {/* Grade, Tags */}
      <div className="form-field">
        <label className="field-label">{t('common.grade')}</label>
        <select value={form.grade}
          onChange={e => setForm(f => ({ ...f, grade: e.target.value }))}
          className={inputCls}>
          <option value="">— {t('common.select')} —</option>
          <option value="1">1</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="4">4</option>
        </select>
      </div>
      <div className="form-field">
        <CheckboxGroup label={t('common.tag')} options={['Sales','Client','Technical','Head','Internal Sales']}
          selected={form.tags} onChange={v => setForm(f => ({ ...f, tags: v }))}
          showCustom onAddCustom={v => setForm(f => f.tags.includes(v) ? f : { ...f, tags: [...f.tags, v] })} />
      </div>

      {/* No. (full width) */}
      <div className="form-field gcol-1-1">
        <CheckboxGroup label={t('common.number')} options={['1','2','3','4','5','6','7','8']}
          selected={form.numbers} onChange={v => setForm(f => ({ ...f, numbers: v }))} />
      </div>

      {/* Email, Phone */}
      <div className="form-field">
        <label className="field-label">{t('common.email')}</label>
        <input type="email" value={form.email}
          onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderEmail')} />
      </div>
      <div className="form-field">
        <label className="field-label">{t('common.phone')}</label>
        <div className="phone-row">
          <select className="phone-code-select" value={form.country_code}
            onChange={e => setForm(f => ({ ...f, country_code: e.target.value }))}
            aria-label="國家代碼">
            {COUNTRY_CODES.map(c => <option key={c.code + c.name} value={c.code}>{c.name} {c.code}</option>)}
          </select>
          <input type="text" value={form.phone}
            onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
            className={inputCls} placeholder={t('common.placeholderPhone')} />
        </div>
      </div>

      {/* Office Phone, LinkedIn URL */}
      <div className="form-field">
        <label className="field-label">{t('common.office')}</label>
        <input type="text" value={form.office_phone}
          onChange={e => setForm(f => ({ ...f, office_phone: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderOffice')} />
      </div>
      <div className="form-field">
        <label className="field-label">{t('common.linkedin')}</label>
        <input type="text" value={form.linkedin_url}
          onChange={e => setForm(f => ({ ...f, linkedin_url: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderLinkedin')} />
      </div>

      {/* Address, Company */}
      <div className="form-field">
        <label className="field-label">{t('common.address')}</label>
        <input type="text" value={form.address}
          onChange={e => setForm(f => ({ ...f, address: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderAddress')} />
      </div>
      {/* Company search */}
      <div className="form-field">
        <EntitySearch
          searchUrl="/api/v1/crm/companies"
          value={form.company_id}
          onChange={(id) => setForm(f => ({ ...f, company_id: id }))}
          placeholder={t('common.placeholderSearchCompanies')}
          label={t('common.company')}
          createLabel={t('common.company')}
          createTitleField="name"
        />
      </div>

      {/* Notes (full width) */}
      <div className="form-field gcol-1-1">
        <label className="field-label">{t('common.notes')}</label>
        <textarea value={form.notes}
          onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
          className={inputCls} placeholder={t('common.placeholderNotes')} rows={3} />
      </div>
    </div>
  );
}

export default function ContactsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const tableRef = useRef<HTMLTableElement>(null);
  const { query, setQuery, debounced } = useSearch();
  const searchQs = debounced ? `?search=${encodeURIComponent(debounced)}&limit=50` : '?limit=50';
  const { data, loading, error, refresh } = useApi<ContactListResponse>(`/api/v1/crm/contacts${searchQs}`);

  const create = useCreateModal();
  const [editTarget, setEditTarget] = useState<Contact | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);
  const [form, setForm] = useState(defaultForm);
  const [queue, setQueue] = useState<typeof defaultForm[]>([]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);


  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  // ── Multi-select state ──
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const col = useColumnConfig();
  const visibleCols = col.getVisible();
  // Map column keys to i18n labels
  const colLabel = (key: string): string => {
    const map: Record<string, string> = {
      name: t('pages.contacts.name'),
      company: t('pages.contacts.company'),
      email: t('pages.contacts.email'),
      status: t('pages.contacts.status'),
      last_touch: t('pages.contacts.lastTouch'),
    };
    return map[key] || key;
  };
  // Map column keys to render functions
  const colRender: Record<string, (c: Contact) => React.ReactNode> = {
    name: c => (
      <button onClick={() => setSelectedContactId(c.id)}
        className="row-name row-name-btn">
        <div className="avatar-sm">
          {c.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()}
        </div>
        <span className="row-name-text">{c.name}</span>
      </button>
    ),
    company: c => <span>{c.company?.name || '—'}</span>,
    email: c => <span className="row-email">{c.email || '—'}</span>,
    status: c => <span className={`select-tag ${statusColors[c.status] || 'tag-default'}`}>{c.status || 'Active'}</span>,
    last_touch: c => <span className="last-touch">{formatDate(c.last_touch || c.created_at)}</span>,
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length && items.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map(i => i.id)));
    }
  };

  const buildPayloadOf = (f: typeof defaultForm) => ({
    name: f.name,
    email: f.email || null,
    phone: f.phone.trim() ? (f.country_code + f.phone.replace(/[\s-]/g, '')) : null,
    status: f.status.toLowerCase(),
    company_id: f.company_id || null,
    chinese_name: f.chinese_name || null,
    nick_name: f.nick_name || null,
    contact_type: f.contact_type || null,
    grade: f.grade || null,
    numbers: f.numbers.length > 0 ? f.numbers : [],
    office_phone: f.office_phone || null,
    job_title: f.job_title || null,
    department: f.department || null,
    linkedin_url: f.linkedin_url || null,
    address: f.address || null,
    notes: f.notes || null,
    tags: f.tags.length > 0 ? f.tags : [],
  });

  const closeCreate = () => { setQueue([]); setForm(defaultForm); create.closeModal(); };

  // ---- Create (single or multi — 2026-09-11) ----
  const handleCreate = async () => {
    const staged = [...queue];
    if (form.name.trim()) staged.push(form);
    if (staged.length === 0) return;
    setSaving(true);
    try {
      const payloads = staged.map(buildPayloadOf);
      // 1 contact → object (legacy contract); 2+ → array (multi-add)
      await apiClient.post('/api/v1/crm/contacts', payloads.length === 1 ? payloads[0] : payloads);
      setForm(defaultForm);
      setQueue([]);
      create.closeModal();
      refresh();
    } catch (e: any) {
      alert(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  };

  // ---- Edit ----
  const handleEdit = async () => {
    if (!editTarget || !form.name.trim()) return;
    setSaving(true);
    try {
      await apiClient.patch(`/api/v1/crm/contacts/${editTarget.id}`, buildPayloadOf(form));
      setEditTarget(null);
      refresh();
    } catch (e: any) {
      alert(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (c: Contact) => {
    const sp = splitPhone(c.phone || '', '+852');
    setForm({
      name: c.name,
      email: c.email || '',
      phone: sp.local,
      status: c.status || 'Active',
      company_id: c.company?.id || '',
      chinese_name: c.chinese_name || '',
      nick_name: c.nick_name || '',
      contact_type: c.contact_type || '',
      grade: c.grade || '',
      numbers: c.numbers || [],
      office_phone: c.office_phone || '',
      job_title: c.job_title || '',
      department: c.department || '',
      linkedin_url: c.linkedin_url || '',
      address: c.address || '',
      notes: c.notes || '',
      tags: c.tags || [],
      country_code: sp.code,
    });
    setEditTarget(c);
  };

  // ---- Delete ----
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/api/v1/crm/contacts/${deleteTarget.id}`);
      setDeleteTarget(null);
      refresh();
    } catch (e: any) {
      alert(e.detail || e.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>{t('common.home')}</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">{t('pages.contacts.title')}</span>
      </div>

      {/* Header */}
      <div className="page-header">
        <div>
          <h1>{t('pages.contacts.title')}</h1>
          <p>{t('pages.contacts.count', { count: total })}</p>
        </div>
        <div className="header-actions">
          <button className="btn-secondary">
            <SvcIcon name="download" className="w-4 h-4" /> {t('common.export')}
          </button>
          <button onClick={create.openModal} className="btn-primary">
            <SvcIcon name="plus" className="w-4 h-4" /> {t('pages.contacts.new')}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="data-table">
        {/* DB Toolbar */}
        <div className="db-toolbar">
          <div className="db-search">
            <SvcIcon name="search" className="w-4 h-4" />
            <input type="text" placeholder={t('pages.contacts.searchPlaceholder')} value={query}
              onChange={e => setQuery(e.target.value)} />
          </div>
          <div className="toolbar-actions">
            <button className="toolbar-btn"><SvcIcon name="filter" className="w-4 h-4" /> {t('common.filter')}</button>
            <button className="toolbar-btn"><SvcIcon name="arrow-up-down" className="w-4 h-4" /> {t('common.sort')}</button>
            <button className="toolbar-btn"><SvcIcon name="layout-grid" className="w-4 h-4" /> {t('common.group')}</button>
            <span className="toolbar-sep" />
            <button className="toolbar-btn" onClick={col.openMobile}><SvcIcon name="sliders-horizontal" className="w-4 h-4" /> {t('common.properties')}</button>
          </div>
        </div>

        {loading ? (
          <TableSkeleton rows={5} cols={6} />
        ) : error ? (
          <ErrorBox message={error} onRetry={refresh} />
        ) : items.length === 0 ? (
          <div className="empty-state">{t('pages.contacts.empty')}</div>
        ) : (
          <>
            <table ref={tableRef}>
              <colgroup>
                <col style={{ width: 40 }} />
                {visibleCols.map(v => <col key={v.key} style={{ width: v.width }} />)}
                <col style={{ width: 44 }} />
              </colgroup>
              <thead>
                <tr>
                  <th className="th-checkbox" style={{ width: 40 }}>
                    <input type="checkbox" className="row-checkbox"
                      checked={items.length > 0 && selectedIds.size === items.length}
                      onChange={toggleSelectAll} />
                  </th>
                  {visibleCols.map(v => (
                    <th key={v.key}
                      draggable
                      data-col-key={v.key}
                      onDragStart={e => col.onDragStart(e, v.key)}
                      onDragOver={e => col.onDragOver(e, v.key)}
                      onDragEnd={col.onDragEnd}
                      className="col-draggable">
                      <span className="col-label">{colLabel(v.key)}</span>
                      <span className="col-resize-handle" onMouseDown={e => col.onResizeStart(e, v.key)} />
                    </th>
                  ))}
                  <th className="col-menu" style={{ width: 44 }}></th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id} className={selectedIds.has(c.id) ? 'row-selected' : ''}>
                    <td className="th-checkbox" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" className="row-checkbox"
                        checked={selectedIds.has(c.id)}
                        onChange={() => toggleSelect(c.id)} />
                    </td>
                    {visibleCols.map(v => (
                      <td key={v.key}>{colRender[v.key]?.(c) ?? '—'}</td>
                    ))}
                    <td className="col-menu" onClick={e => e.stopPropagation()}>
                      <div className="menu-wrap">
                        <button className="menu-dots" title={t('common.moreActions')}>
                          <SvcIcon name="more-horizontal" className="w-4 h-4" />
                        </button>
                        <div className="menu-dropdown">
                          <button className="menu-item" onClick={() => openEdit(c)}>
                            <SvcIcon name="edit-3" /> {t('common.edit')}
                          </button>
                          <button className="menu-item text-notification" onClick={() => setDeleteTarget(c)}>
                            <SvcIcon name="trash-2" /> {t('common.delete')}
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Bulk action bar */}
            {selectedIds.size > 0 && (
              <div className="bulk-bar">
                <span className="count">{t('pages.contacts.selectedCount', { count: selectedIds.size })}</span>
                <button className="btn-secondary">{t('common.addTag')}</button>
                <button className="btn-secondary">{t('common.export')}</button>
                <button className="btn-notification"
                  onClick={() => {
                    const first = items.find(i => selectedIds.has(i.id));
                    if (first) setDeleteTarget(first);
                  }}>
                  <SvcIcon name="trash-2" className="w-4 h-4" /> {t('common.delete')}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* ─── Create Modal ─── */}
      {create.open && (
        <div className="modal-overlay"
          onClick={(e) => { if (e.target === e.currentTarget) closeCreate(); }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.contacts.new')}</h2>
              <button onClick={closeCreate} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body pb-100">
              <ContactFormFields form={form} setForm={setForm} inputCls={inputCls} />

              {/* Multi-add: stage additional contacts before creating (2026-09-11) */}
              <div className="form-field gcol-1-1 multi-add-wrap">
                {queue.length > 0 && (
                  <div className="multi-queue">
                    <div className="multi-queue-head">{t('pages.contacts.multi.queued', { count: queue.length })}</div>
                    {queue.map((q, i) => (
                      <div key={i} className="multi-queue-row">
                        <span className="multi-queue-name">{q.name}</span>
                        <button type="button" className="multi-queue-remove"
                          aria-label={t('pages.contacts.multi.remove')}
                          onClick={() => setQueue(arr => arr.filter((_, idx) => idx !== i))}>
                          <SvcIcon name="x" className="icon-16" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <button type="button" className="btn-secondary multi-add-btn"
                  disabled={!form.name.trim()}
                  onClick={() => { setQueue(arr => [...arr, { ...form }]); setForm(defaultForm); }}>
                  <SvcIcon name="plus" className="w-4 h-4" /> {t('pages.contacts.multi.addAnother')}
                </button>
                <div className="multi-hint">{t('pages.contacts.multi.hint')}</div>
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={closeCreate} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleCreate} disabled={saving || (!form.name.trim() && queue.length === 0)}
                className="btn-primary">
                {saving ? t('common.saving') : t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Edit Modal ─── */}
      {editTarget && (
        <div className="modal-overlay"
          onClick={(e) => { if (e.target === e.currentTarget) setEditTarget(null); }}>
          <div className="modal">
            <div className="modal-head">
              <h2>{t('common.edit')}</h2>
              <button onClick={() => setEditTarget(null)} className="modal-x"><SvcIcon name="x" className="icon-16" /></button>
            </div>
            <div className="modal-body form-body pb-100">
              <ContactFormFields form={form} setForm={setForm} inputCls={inputCls} />
            </div>
            <div className="modal-foot">
              <button onClick={() => setEditTarget(null)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleEdit} disabled={saving || !form.name.trim()}
                className="btn-primary">
                {saving ? t('common.saving') : t('common.save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Delete Confirmation ─── */}
      {deleteTarget && (
        <div className="modal-overlay"
          onClick={(e) => { if (e.target === e.currentTarget) setDeleteTarget(null); }}>
          <div className="modal modal-sm">
            <div className="delete-body">
              <div className="delete-icon-wrap">
                <SvcIcon name="trash-2" />
              </div>
              <h2 className="delete-heading">{t('pages.contacts.deleteTitle')}</h2>
              <p className="delete-text">
                {t('pages.contacts.deleteConfirmText')} <strong>{deleteTarget.name}</strong>?
                {t('pages.contacts.deleteCannotUndo')}
              </p>
            </div>
            <div className="modal-foot">
              <button onClick={() => setDeleteTarget(null)} className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleDelete} disabled={deleting}
                className="btn-notification">
                {deleting ? t('common.deleting') : t('common.delete')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Mobile Column Settings ─── */}
      <BottomSheet open={col.mobileOpen} onClose={col.closeMobile} title={t('common.columns')}>
        <div className="col-settings">
          {visibleCols.map((v, i) => (
            <div key={v.key} className="col-settings-row">
              <SvcIcon name="grip-vertical" className="w-4 h-4 col-grip" />
              <span className="col-settings-label">{colLabel(v.key)}</span>
              <div className="col-settings-arrows">
                <button className="col-arrow" disabled={i === 0}
                  onClick={() => col.moveMobile(i, -1)}>↑</button>
                <button className="col-arrow" disabled={i === visibleCols.length - 1}
                  onClick={() => col.moveMobile(i, 1)}>↓</button>
              </div>
            </div>
          ))}
          <button className="quick-submit" onClick={() => { col.resetColumns(); col.closeMobile(); }}
            style={{ marginTop: 16, background: 'var(--color-surface-offset)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
            {t('common.resetColumns')}
          </button>
        </div>
      </BottomSheet>

      {/* ─── Right-side Detail Drawer ─── */}
      <SlideDrawer open={!!selectedContactId} onClose={() => setSelectedContactId(null)} title={t('pages.contacts.detailTitle')}>
        {selectedContactId && (
          <DetailDrawerContent
            config={contactConfig}
            id={selectedContactId}
            onClose={() => setSelectedContactId(null)}
          />
        )}
      </SlideDrawer>
    </div>
  );
}
