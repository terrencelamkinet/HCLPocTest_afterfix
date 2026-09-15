import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../components/SvcIcon';
import { useNavigate } from 'react-router-dom';
import { useApi, useSearch, useCreateModal, TableSkeleton, ErrorBox } from '../lib/useApi';
import { apiClient } from '../lib/api';

interface Company {
  id: string;
  name: string;
  industry: string | null;
  domain: string | null;
  status: string;
  created_at: string;
}

interface CompanyListResponse {
  items: Company[];
  total: number;
  page: number;
  page_size: number;
}

const statusColors: Record<string, string> = {
  Active: 'badge-active',
  '': 'badge-p3',
};

const defaultForm = { name: '', industry: '', domain: '', status: 'Active' };

export default function CompaniesPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { query, setQuery, searchParams } = useSearch();
  const { data, loading, error, refresh } = useApi<CompanyListResponse>(`/api/v1/crm/companies${searchParams}`);
  const create = useCreateModal();
  const [form, setForm] = useState(defaultForm);
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await apiClient.post('/api/v1/crm/companies', {
        name: form.name,
        industry: form.industry || null,
        domain: form.domain || null,
        status: form.status === 'Active' ? 'active' : 'inactive',
      });
      setForm(defaultForm);
      create.closeModal();
      refresh();
    } catch (e: any) {
      alert(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  };

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="page-content">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">Companies</span>
      </div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>{t('pages.companies.title')}</h1>
          <p>{t('pages.companies.count', { count: total })}</p>
        </div>
        <div className="header-actions">
          <button
            onClick={create.openModal}
            className="btn-primary"
          >
            <SvcIcon name="plus" className="w-4 h-4" /> {t('pages.companies.new')}
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="data-table">
        <div className="panel-head">
          <div className="search-box">
            <SvcIcon name="search" className="w-4 h-4" />
            <input
              type="text"
              placeholder="Search companies..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <TableSkeleton rows={5} cols={6} />
        ) : error ? (
          <ErrorBox message={error} onRetry={refresh} />
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-400">No companies found</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Industry</th>
                <th className="hidden md:table-cell">Domain</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="row-name">
                      <div className="list-icon">
                        <SvcIcon name="building-2" className="w-4 h-4" />
                      </div>
                      <span>{c.name}</span>
                    </div>
                  </td>
                  <td>{c.industry || '—'}</td>
                  <td className="hidden md:table-cell">{c.domain || '—'}</td>
                  <td>
                    <span className={`badge ${statusColors[c.status] || 'badge-p3'}`}>
                      {c.status || 'Active'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create Modal */}
      {create.open && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.companies.new')}</h2>
              <button onClick={create.closeModal} className="modal-x"><SvcIcon name="x" className="w-5 h-5" /></button>
            </div>
            <div className="modal-body">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Name *</label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-highlight focus:border-primary"
                    placeholder="Company name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Industry</label>
                  <input
                    type="text"
                    value={form.industry}
                    onChange={e => setForm(f => ({ ...f, industry: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-highlight focus:border-primary"
                    placeholder="e.g. IT Solutions"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Domain</label>
                  <input
                    type="text"
                    value={form.domain}
                    onChange={e => setForm(f => ({ ...f, domain: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-highlight focus:border-primary"
                    placeholder="e.g. kinetix.com"
                  />
                </div>
              </div>
            </div>
            <div className="modal-foot">
              <button
                onClick={create.closeModal}
                className="btn-secondary"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={saving || !form.name.trim()}
                className="btn-primary"
              >
                {saving ? t('common.processing') : t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
