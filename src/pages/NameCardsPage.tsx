import { useRef, useState, useEffect } from 'react';
import SvcIcon from '../components/SvcIcon';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useApi, CardSkeleton, ErrorBox } from '../lib/useApi';
import { uploadFile, apiClient } from '../lib/api';
import { useEscapeKey } from '../lib/useEscapeKey';

interface NameCard {
  id: string;
  name: string;
  title: string | null;
  company: string | null;
  phone: string | null;
  email: string | null;
  image_url: string | null;
  original_image_url: string | null;
  cropped_image_url: string | null;
  display_image: string | null; // 'original' | 'cropped'
  raw_ocr_text: string | null;
  parsed_data: Record<string, any> | null;
  review_candidates: any[] | null;
  status: string; // pending | matched | created | review
  contact_id: string | null;
  created_at: string;
}

interface NameCardListResponse {
  items: NameCard[];
  total: number;
}

const STATUS_META: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  created: { icon: <SvcIcon name="user-plus" size={13} />, label: '已建立聯絡人', color: 'var(--color-success)' },
  matched: { icon: <SvcIcon name="link-2" size={13} />, label: '已連結聯絡人', color: 'var(--color-primary)' },
  review: { icon: <SvcIcon name="file-warning" size={13} />, label: '⚠️ 待確認', color: 'var(--color-warning, #b58a2a)' },
  pending: { icon: <SvcIcon name="file-warning" size={13} />, label: '待處理', color: 'var(--color-warning, #b58a2a)' },
};

export default function NameCardsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, loading, error, refresh } = useApi<NameCardListResponse>('/api/v1/crm/name-cards?limit=100');

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [selected, setSelected] = useState<NameCard | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ESC closes the detail modal first, then the upload modal (stack order).
  useEscapeKey(() => {
    if (selected) setSelected(null);
    else if (uploadOpen) setUploadOpen(false);
  }, !!(uploadOpen || selected));

  const handleFile = async (file: File | undefined | null) => {
    if (!file) return;
    setUploading(true);
    setUploadError('');
    try {
      await uploadFile<NameCard>('/api/v1/crm/name-cards/upload', file);
      setUploadOpen(false);
      refresh();
    } catch (e: any) {
      const detail = e?.detail || e?.message || '上載失敗';
      setUploadError(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const openCard = async (card: NameCard) => {
    // Fetch fresh detail (includes contact link state)
    try {
      const detail = await apiClient.get<NameCard>(`/api/v1/crm/name-cards/${card.id}`);
      setSelected(detail);
    } catch {
      setSelected(card);
    }
  };

  // ── Dual-image helpers ────────────────────────────────────────────────
  const displayUrl = (card: NameCard) =>
    card.display_image === 'cropped' && card.cropped_image_url
      ? card.cropped_image_url
      : (card.original_image_url || card.image_url || undefined);

  const refreshDetail = async (cardId: string) => {
    try {
      const detail = await apiClient.get<NameCard>(`/api/v1/crm/name-cards/${cardId}`);
      setSelected(detail);
      refresh();
    } catch { /* keep current */ }
  };

  const setDefault = async (variant: 'original' | 'cropped') => {
    if (!selected) return;
    try {
      await apiClient.patch(`/api/v1/crm/name-cards/${selected.id}`, { display_image: variant });
      await refreshDetail(selected.id);
    } catch (e: any) {
      alert(e?.detail || e?.message || '設定失敗');
    }
  };

  const deleteImage = async (variant: 'original' | 'cropped') => {
    if (!selected) return;
    const label = variant === 'original' ? '原裝' : '裁剪版';
    if (!window.confirm(t('nameCard.confirmDeleteImage', { label, defaultValue: '刪除{{label}}圖片？刪除後另一張會自動成為預設。' }))) return;
    try {
      await apiClient.delete(`/api/v1/crm/name-cards/${selected.id}/image/${variant}`);
      await refreshDetail(selected.id);
    } catch (e: any) {
      alert(e?.detail || e?.message || '刪除失敗');
    }
  };

  const deleteAllImages = async () => {
    if (!selected) return;
    if (!window.confirm(t('nameCard.confirmDeleteAll', { defaultValue: '刪除全部圖片？此動作無法復原。' }))) return;
    try {
      const id = selected.id;
      if (selected.cropped_image_url) await apiClient.delete(`/api/v1/crm/name-cards/${id}/image/cropped`);
      if (selected.original_image_url) await apiClient.delete(`/api/v1/crm/name-cards/${id}/image/original`);
      await refreshDetail(id);
    } catch (e: any) {
      alert(e?.detail || e?.message || '刪除失敗');
    }
  };

  const recrop = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await apiClient.post(`/api/v1/crm/name-cards/${selected.id}/recrop`);
      await refreshDetail(selected.id);
    } catch (e: any) {
      alert(e?.detail || e?.message || '裁剪失敗');
    } finally {
      setBusy(false);
    }
  };

  const resolveReview = async (action: 'overwrite' | 'keep_both') => {
    if (!selected || !selected.review_candidates?.length) return;
    const cand = selected.review_candidates[0];
    const label = action === 'overwrite' ? t('nameCard.overwriteExisting', { defaultValue: '覆蓋現有聯絡人' }) : t('nameCard.saveBoth', { defaultValue: '兩者保存' });
    if (!window.confirm(`${label}？確定執行？`)) return;
    setBusy(true);
    try {
      await apiClient.post(`/api/v1/crm/name-cards/${selected.id}/resolve`, {
        action,
        contact_id: action === 'overwrite' ? cand.contact_id : undefined,
      });
      await refreshDetail(selected.id);
    } catch (e: any) {
      alert(e?.detail || e?.message || '操作失敗');
    } finally {
      setBusy(false);
    }
  };

  const [busy, setBusy] = useState(false);
  const [zoomImage, setZoomImage] = useState<string | null>(null);

  // Close lightbox on Escape
  useEffect(() => {
    if (!zoomImage) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setZoomImage(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [zoomImage]);

  return (
    <div className="page-content">
      <div className="breadcrumb">
        <span className="breadcrumb-link" onClick={() => navigate('/dashboard')}>Home</span>
        <SvcIcon name="chevron-right" />
        <span className="breadcrumb-current">Name Cards</span>
      </div>

      <div className="page-header">
        <div>
          <h1>{t('nameCard.scannerTitle')}</h1>
          <p>{t('nameCard.scannedCount', { count: total })}</p>
        </div>
        <button className="btn-primary" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} onClick={() => setUploadOpen(true)}>
          <SvcIcon name="upload" size={15} />{t('nameCard.addCard', { defaultValue: '新增卡片' })}
        </button>
      </div>

      {/* Upload modal */}
      {uploadOpen && (
        <div className="modal-overlay" onClick={() => !uploading && setUploadOpen(false)}>
          <div className="modal" style={{ maxWidth: 460 }} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="modal-head">
              <h2>{t('nameCard.uploadCard', { defaultValue: '上載名片' })}</h2>
              <button className="modal-x" onClick={() => setUploadOpen(false)} aria-label="Close"><SvcIcon name="x" size={18} /></button>
            </div>
            <div className="modal-body">
              <p className="hint" style={{ marginTop: 0 }}>{t('nameCard.uploadHint', { defaultValue: '上載卡片圖片後會自動 OCR 提取資料，並建立或連結對應聯絡人。' })}</p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={e => handleFile(e.target.files?.[0])}
                disabled={uploading}
                style={{ width: '100%', padding: '10px 0' }}
              />
              {uploading && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-text-muted)', fontSize: 13 }}>
                  <SvcIcon name="loader-2" size={15} className="spin" />{t('nameCard.ocrProcessing', { defaultValue: 'OCR 辨識中...' })}
                </div>
              )}
              {uploadError && <p className="asec-error" style={{ color: 'var(--color-error, #ab4b59)' }}>{uploadError}</p>}
            </div>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {selected && (
        <div className="modal-overlay" onClick={() => setSelected(null)}>
          <div className="modal" style={{ maxWidth: 560 }} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true">
            <div className="modal-head">
              <h2>{selected.parsed_data?.name || selected.name || '名片詳情'}</h2>
              <button className="modal-x" onClick={() => setSelected(null)} aria-label="Close"><SvcIcon name="x" size={18} /></button>
            </div>
            <div className="modal-body">
              {/* Dual-image viewer: original + cropped side by side */}
              {(selected.original_image_url || selected.cropped_image_url) && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
                  {selected.original_image_url && (
                    <div style={{ border: '1px solid var(--color-divider)', borderRadius: 8, overflow: 'hidden' }}>
                      <div style={{ position: 'relative', minHeight: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--color-surface-dynamic)' }}>
                        <img
                          src={selected.original_image_url}
                          alt={t('nameCard.originalCardAlt', { defaultValue: '原裝名片' })}
                          style={{ maxWidth: '100%', maxHeight: 170, objectFit: 'contain', cursor: 'zoom-in' }}
                          onClick={() => setZoomImage(selected.original_image_url!)}
                        />
                        <span style={{ position: 'absolute', bottom: 6, right: 6, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10.5, color: 'var(--color-text-muted)', background: 'rgba(255,255,255,0.75)', borderRadius: 999, padding: '2px 7px' }}>
                          <SvcIcon name="zoom-in" size={11} />{t('nameCard.zoomIn', { defaultValue: '放大' })}
                        </span>
                        {selected.display_image === 'original' && (
                          <span style={{ position: 'absolute', top: 6, left: 6, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, fontWeight: 600, color: '#fff', background: 'var(--color-success)', borderRadius: 999, padding: '2px 8px' }}>
                            <SvcIcon name="check" size={11} />{t('nameCard.default', { defaultValue: '預設' })}
                          </span>
                        )}
                      </div>
                      <div style={{ padding: '7px 9px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 600 }}>{t('nameCard.original', { defaultValue: '🖼 原裝' })}</span>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {selected.display_image !== 'original' && (
                            <button className="btn-ghost" style={{ fontSize: 11.5, padding: '3px 8px' }} onClick={() => setDefault('original')}>{t('nameCard.setDefault', { defaultValue: '設為預設' })}</button>
                          )}
                          <button className="btn-ghost" style={{ fontSize: 11.5, padding: '3px 8px', color: 'var(--color-error, #ab4b59)' }} onClick={() => deleteImage('original')} aria-label={t('nameCard.deleteOriginal', { defaultValue: '刪除原裝' })}>
                            <SvcIcon name="trash-2" size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                  {selected.cropped_image_url && (
                    <div style={{ border: '1px solid var(--color-divider)', borderRadius: 8, overflow: 'hidden' }}>
                      <div style={{ position: 'relative', minHeight: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--color-surface-dynamic)' }}>
                        <img
                          src={selected.cropped_image_url}
                          alt={t('nameCard.croppedCardAlt', { defaultValue: '裁剪版名片' })}
                          style={{ maxWidth: '100%', maxHeight: 170, objectFit: 'contain', cursor: 'zoom-in' }}
                          onClick={() => setZoomImage(selected.cropped_image_url!)}
                        />
                        <span style={{ position: 'absolute', bottom: 6, right: 6, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10.5, color: 'var(--color-text-muted)', background: 'rgba(255,255,255,0.75)', borderRadius: 999, padding: '2px 7px' }}>
                          <SvcIcon name="zoom-in" size={11} />{t('nameCard.zoomIn', { defaultValue: '放大' })}
                        </span>
                        {selected.display_image === 'cropped' && (
                          <span style={{ position: 'absolute', top: 6, left: 6, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, fontWeight: 600, color: '#fff', background: 'var(--color-success)', borderRadius: 999, padding: '2px 8px' }}>
                            <SvcIcon name="check" size={11} />{t('nameCard.default', { defaultValue: '預設' })}
                          </span>
                        )}
                      </div>
                      <div style={{ padding: '7px 9px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 600 }}>{t('nameCard.cropped', { defaultValue: '✂️ 裁剪版' })}</span>
                        <div style={{ display: 'flex', gap: 4 }}>
                          {selected.display_image !== 'cropped' && (
                            <button className="btn-ghost" style={{ fontSize: 11.5, padding: '3px 8px' }} onClick={() => setDefault('cropped')}>{t('nameCard.setDefault', { defaultValue: '設為預設' })}</button>
                          )}
                          <button className="btn-ghost" style={{ fontSize: 11.5, padding: '3px 8px', color: 'var(--color-error, #ab4b59)' }} onClick={() => deleteImage('cropped')} aria-label={t('nameCard.deleteCropped', { defaultValue: '刪除裁剪版' })}>
                            <SvcIcon name="trash-2" size={13} />
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {/* No crop yet → offer to generate one (legacy cards fall back to image_url) */}
              {(selected.original_image_url || selected.image_url) && !selected.cropped_image_url && (
                <div style={{ textAlign: 'center', marginBottom: 14 }}>
                  <button className="btn-ghost" style={{ fontSize: 12.5 }} onClick={recrop} disabled={busy}>
                    {busy ? <SvcIcon name="loader-2" size={13} className="spin" style={{ verticalAlign: -2 }} /> : <SvcIcon name="wand-2" size={13} style={{ verticalAlign: -2 }} />} 生成裁剪版
                  </button>
                </div>
              )}
              {/* Delete everything */}
              {(selected.original_image_url || selected.cropped_image_url) && (
                <div style={{ textAlign: 'center', marginBottom: 14 }}>
                  <button className="btn-ghost" style={{ fontSize: 12.5, color: 'var(--color-error, #ab4b59)' }} onClick={deleteAllImages}>
                    <SvcIcon name="trash-2" size={13} style={{ verticalAlign: -2 }} />{t('nameCard.deleteAllImages', { defaultValue: '刪除全部圖片' })}
                  </button>
                </div>
              )}
              {/* LLM duplicate review — user decides overwrite vs keep both */}
              {selected.status === 'review' && (selected.review_candidates ?? []).length > 0 && (() => {
                const cand = (selected.review_candidates ?? [])[0];
                const pd = selected.parsed_data || {};
                return (
                  <div style={{ border: '1px solid var(--color-warning, #b58a2a)', borderRadius: 8, padding: 12, marginBottom: 14, background: 'rgba(181,138,42,0.06)' }}>
                    <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t('nameCard.possibleDuplicate', { defaultValue: '⚠️ 可能係重複聯絡人' })}</p>
                    <p style={{ fontSize: 12.5, color: 'var(--color-text-muted)', marginBottom: 10 }}>
                      AI 發現呢張卡可能同現有聯絡人相同{cand.reason ? ` — ${cand.reason}` : ''}
                    </p>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 12.5, marginBottom: 10 }}>
                      <div style={{ padding: 8, background: 'var(--color-surface-offset)', borderRadius: 6 }}>
                        <p style={{ fontWeight: 600, marginBottom: 4 }}>{t('nameCard.existingContact', { defaultValue: '現有聯絡人' })}</p>
                        <p>{cand.name || '—'}</p>
                        <p style={{ color: 'var(--color-text-muted)', wordBreak: 'break-all' }}>{cand.email || '—'} · {cand.phone || '—'}</p>
                        <p style={{ color: 'var(--color-text-muted)' }}>{cand.company || cand.title || ''}</p>
                      </div>
                      <div style={{ padding: 8, background: 'var(--color-surface-offset)', borderRadius: 6 }}>
                        <p style={{ fontWeight: 600, marginBottom: 4 }}>{t('nameCard.cardData', { defaultValue: '名片資料' })}</p>
                        <p>{pd.name || '—'}</p>
                        <p style={{ color: 'var(--color-text-muted)', wordBreak: 'break-all' }}>{pd.email || '—'} · {pd.phone || '—'}</p>
                        <p style={{ color: 'var(--color-text-muted)' }}>{pd.company || pd.title || ''}</p>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <button className="btn-primary" style={{ fontSize: 12.5, padding: '6px 12px' }} disabled={busy} onClick={() => resolveReview('overwrite')}>{t('nameCard.overwriteExisting', { defaultValue: '覆蓋現有聯絡人' })}</button>
                      <button className="btn-ghost" style={{ fontSize: 12.5, padding: '6px 12px' }} disabled={busy} onClick={() => resolveReview('keep_both')}>{t('nameCard.saveBoth', { defaultValue: '兩者保存' })}</button>
                    </div>
                  </div>
                );
              })()}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                {(() => {
                  const meta = STATUS_META[selected.status] || STATUS_META.pending;
                  return (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: meta.color }}>
                      {meta.icon} {meta.label}
                    </span>
                  );
                })()}
                {selected.contact_id && (
                  <button
                    className="btn-ghost"
                    style={{ fontSize: 12, padding: '3px 10px' }}
                    onClick={() => navigate(`/contacts/${selected.contact_id}`)}
                  >{t('nameCard.openContact', { defaultValue: '開啟聯絡人 →' })}</button>
                )}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '6px 12px', fontSize: 13.5 }}>
                {[
                  ['職稱', selected.parsed_data?.title || selected.title],
                  ['公司', selected.parsed_data?.company || selected.company],
                  ['電話', selected.parsed_data?.phone || selected.phone],
                  ['電郵', selected.parsed_data?.email || selected.email],
                  ['網站', selected.parsed_data?.website],
                  ['LinkedIn', selected.parsed_data?.linkedin],
                  ['中文名', selected.parsed_data?.chinese_name],
                ].filter(([, v]) => v).map(([k, v]) => (
                  <div key={k as string} style={{ display: 'contents' }}>
                    <span style={{ color: 'var(--color-text-muted)' }}>{k}</span>
                    <span style={{ wordBreak: 'break-all' }}>{v as string}</span>
                  </div>
                ))}
              </div>
              {selected.raw_ocr_text && (
                <details style={{ marginTop: 12 }}>
                  <summary style={{ fontSize: 12.5, cursor: 'pointer', color: 'var(--color-text-muted)' }}>{t('nameCard.ocrRaw', { defaultValue: 'OCR 原文' })}</summary>
                  <pre style={{ fontSize: 11.5, whiteSpace: 'pre-wrap', background: 'var(--color-surface-offset)', padding: 10, borderRadius: 6, marginTop: 6, maxHeight: 180, overflow: 'auto' }}>{selected.raw_ocr_text}</pre>
                </details>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Lightbox: click-to-zoom fullscreen view — contain fit keeps aspect ratio */}
      {zoomImage && (
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 2000, background: 'rgba(0,0,0,0.88)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out' }}
          onClick={() => setZoomImage(null)}
          role="dialog"
          aria-modal="true"
        >
          <img
            src={zoomImage}
            alt={t('nameCard.zoomViewAlt', { defaultValue: '名片放大檢視' })}
            style={{ maxWidth: '94vw', maxHeight: '90vh', objectFit: 'contain', borderRadius: 4, boxShadow: '0 8px 40px rgba(0,0,0,0.5)' }}
            onClick={e => e.stopPropagation()}
          />
          <button
            onClick={() => setZoomImage(null)}
            aria-label={t('common.close', { defaultValue: '關閉' })}
            style={{ position: 'fixed', top: 14, right: 14, width: 38, height: 38, borderRadius: '50%', border: 'none', background: 'rgba(255,255,255,0.15)', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <SvcIcon name="x" size={20} />
          </button>
        </div>
      )}

      {loading ? (
        <CardSkeleton count={6} />
      ) : error ? (
        <ErrorBox message={error} onRetry={refresh} />
      ) : items.length === 0 ? (
        <div className="p-8 text-center text-sm c-text-faint">
          {t('nameCard.empty')}
          <div style={{ marginTop: 12 }}>
            <button className="btn-primary" onClick={() => setUploadOpen(true)}>{t('nameCard.uploadFirst', { defaultValue: '上載第一張名片' })}</button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {items.map((card) => {
            const meta = STATUS_META[card.status] || STATUS_META.pending;
            return (
              <div key={card.id} className="panel" style={{ cursor: 'pointer', overflow: 'hidden' }} onClick={() => openCard(card)}>
                <div style={{ height: 170, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--color-surface-dynamic)', position: 'relative' }}>
                  {displayUrl(card) ? (
                    <img
                      src={displayUrl(card)}
                      alt={card.name}
                      style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                      loading="lazy"
                    />
                  ) : (
                    <span style={{ fontSize: 32 }}>📇</span>
                  )}
                  <span style={{ position: 'absolute', top: 8, right: 8, display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, fontWeight: 600, color: '#fff', background: meta.color, borderRadius: 999, padding: '2px 8px' }}>
                    {meta.icon} {meta.label}
                  </span>
                </div>
                <div className="p-3 space-y-1">
                  <p className="list-title" style={{ fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {card.parsed_data?.name || card.name || '未辨識'}
                  </p>
                  <p className="list-sub" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {card.parsed_data?.title || card.title || '—'}
                  </p>
                  <p className="text-xs font-medium" style={{ color: 'var(--color-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {card.parsed_data?.company || card.company || '—'}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
