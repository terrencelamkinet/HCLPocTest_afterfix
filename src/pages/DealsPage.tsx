import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import SvcIcon from '../components/SvcIcon';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../lib/api';
import { useCreateModal, ErrorBox } from '../lib/useApi';
import EntitySearch from '../modules/shared/EntitySearch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Pipeline {
  id: string;
  name: string;
}

interface Stage {
  id: string;
  name: string;
  probability: number;
  order_index: number;
}

interface Deal {
  id: string;
  name: string;
  amount: number | null;
  probability: number;
  stage_id: string;
  company?: { id: string; name: string } | null;
  contact?: { id: string; name: string } | null;
  status: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DealsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const create = useCreateModal();
  const [form, setForm] = useState({ name: '', amount: '', company_id: '', contact_id: '', stage_id: '' });
  const [saving, setSaving] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Fetch pipelines
      const pipeRes = await apiClient.get<{ items: Pipeline[]; total: number }>('/api/v1/crm/deal-pipelines?limit=10');
      const pipes = pipeRes.items || [];
      setPipelines(pipes);

      if (pipes.length === 0) {
        setStages([]);
        setDeals([]);
        setLoading(false);
        return;
      }

      const pid = pipelineId || pipes[0].id;
      setPipelineId(pid);

      // 2. Fetch stages for selected pipeline
      const stageRes = await apiClient.get<{ items: Stage[]; total: number }>(`/api/v1/crm/deal-stages?pipeline_id=${pid}&limit=20`);
      const stageList = (stageRes.items || []).sort((a: Stage, b: Stage) => a.order_index - b.order_index);
      setStages(stageList);

      // 3. Fetch deals
      const dealRes = await apiClient.get<{ items: Deal[]; total: number }>('/api/v1/crm/deals?limit=100');
      setDeals(dealRes.items || []);
    } catch (e: any) {
      setError(e.detail || e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);
  useEffect(() => { if (pipelineId) fetchData(); }, [pipelineId]);

  const dealsByStage: Record<string, Deal[]> = {};
  stages.forEach(s => { dealsByStage[s.id] = []; });
  deals.forEach(d => {
    if (d.stage_id && dealsByStage[d.stage_id]) {
      dealsByStage[d.stage_id].push(d);
    }
  });

  const totalAmount = deals.reduce((sum, d) => sum + (d.amount || 0), 0);
  const formatAmount = (n: number | null) => {
    if (!n) return '$0';
    if (n >= 1000000) return `$${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `$${(n / 1000).toFixed(0)}K`;
    return `$${n.toLocaleString()}`;
  };

  const handleCreate = async () => {
    if (!form.name.trim() || !form.stage_id) return;
    setSaving(true);
    try {
      await apiClient.post('/api/v1/crm/deals', {
        name: form.name,
        amount: form.amount ? parseFloat(form.amount) : null,
        company_id: form.company_id || null,
        contact_id: form.contact_id || null,
        stage_id: form.stage_id,
        pipeline_id: pipelineId,
        status: 'open',
      });
      setForm({ name: '', amount: '', company_id: '', contact_id: '', stage_id: '' });
      create.closeModal();
      fetchData();
    } catch (e: any) {
      alert(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="page-content">
        <div className="breadcrumb">
          <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
          <SvcIcon name="chevron-right" />
          <span className="breadcrumb-current">Deals</span>
        </div>
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-slate-200 rounded w-48" />
          <div className="kanban-board">
            {[1,2,3,4].map(i => <div key={i} className="kanban-col" style={{ minHeight: 0 }} />)}
          </div>
        </div>
      </div>
    );
  }

  if (error) return <div className="page-content"><ErrorBox message={error} onRetry={fetchData} /></div>;

  return (
    <div className="page-content">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">Deals</span>
      </div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>{t('pages.deals.title')}</h1>
          <p>{t('pages.deals.summary', { count: deals.length, total: formatAmount(totalAmount) })}</p>
        </div>
        <div className="header-actions">
          {pipelines.length > 1 && (
            <select
              value={pipelineId || ''}
              onChange={e => setPipelineId(e.target.value)}
              className="px-3 py-2 border border-slate-200 rounded-lg text-sm"
            >
              {pipelines.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <button
            onClick={() => {
              if (stages.length > 0) setForm(f => ({ ...f, stage_id: stages[0].id }));
              create.openModal();
            }}
            className="btn-primary"
          >
            <SvcIcon name="plus" className="w-4 h-4" /> {t('pages.deals.new')}
          </button>
        </div>
      </div>

      {/* Kanban Board */}
      {stages.length === 0 ? (
        <div className="text-center text-sm text-slate-400 py-12">No pipeline stages configured</div>
      ) : (
        <div className="kanban-scroll">
          <div className="kanban-board">
            {stages.map((stage) => {
              const stageDeals = dealsByStage[stage.id] || [];
              return (
                <div key={stage.id} className="kanban-col">
                  <div className="kanban-col-head">
                    <span className="title">{stage.name}</span>
                    <span className="count">{stageDeals.length}</span>
                  </div>
                  <div>
                    {stageDeals.length === 0 ? (
                      <div className="p-4 text-center text-xs text-slate-400 border-2 border-dashed border-slate-200 rounded-xl">
                        No deals
                      </div>
                    ) : (
                      stageDeals.map((deal) => (
                        <div key={deal.id} className="deal-card">
                          <p className="name">{deal.name}</p>
                          <p className="company">{deal.company?.name || '—'}</p>
                          <div className="amt-row">
                            <span className="amt">{formatAmount(deal.amount)}</span>
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                                <div className="h-full rounded-full bg-blue-500" style={{ width: `${(deal.probability ?? 0)}%` }} />
                              </div>
                              <span className="text-xs text-slate-500">{(deal.probability ?? 0)}%</span>
                            </div>
                          </div>
                          <div className="owner-row">
                            <span className="text-xs text-slate-400">{deal.contact?.name || '—'}</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Create Modal */}
      {create.open && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-head">
              <h2>{t('pages.deals.new')}</h2>
              <button onClick={create.closeModal} className="modal-x"><SvcIcon name="x" className="w-5 h-5" /></button>
            </div>
            <div className="modal-body pb-100">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Name *</label>
                  <input type="text" value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-highlight focus:border-primary"
                    placeholder="Deal name" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Amount</label>
                  <input type="number" value={form.amount}
                    onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-highlight focus:border-primary"
                    placeholder="e.g. 500000" />
                </div>
                <div>
                  <EntitySearch
                    searchUrl="/api/v1/crm/companies"
                    value={form.company_id}
                    onChange={(id) => setForm(f => ({ ...f, company_id: id }))}
                    placeholder="Search companies..."
                    label="Company"
                    createLabel="Company"
                    createTitleField="name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Stage</label>
                  <select value={form.stage_id}
                    onChange={e => setForm(f => ({ ...f, stage_id: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
                    {stages.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
              </div>
            </div>
            <div className="modal-foot">
              <button onClick={create.closeModal}
                className="btn-secondary">{t('common.cancel')}</button>
              <button onClick={handleCreate} disabled={saving || !form.name.trim()}
                className="btn-primary">
                {saving ? t('common.processing') : t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
