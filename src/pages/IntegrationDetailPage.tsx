import { useParams, Link } from 'react-router-dom';
import { useEffect, useState, useCallback } from 'react';
import SvcIcon from '../components/SvcIcon';
import { availableIntegrations as integrations } from '../data/integrations';
import {
  fetchIntegrations,
  disconnectIntegration,
  fetchGoogleCalendars,
  saveGoogleCalendarSetting,
  syncIntegrationNow,
} from '../lib/integration-api';
import type { IntegrationRecord, GoogleCalendarInfo } from '../lib/integration-api';
import ConnectDialog from '../components/ConnectDialog';

export default function IntegrationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const integration = integrations.find(i => i.id === id);

  const [connection, setConnection] = useState<IntegrationRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);

  // Google Calendar picker state (multi-select)
  const [calendars, setCalendars] = useState<GoogleCalendarInfo[]>([]);
  const [selectedCalIds, setSelectedCalIds] = useState<string[]>([]);
  const [calLoading, setCalLoading] = useState(false);
  const [calSaving, setCalSaving] = useState(false);
  const [calSaved, setCalSaved] = useState(false);
  const [calError, setCalError] = useState<string | null>(null);

  const isGoogleCal = id === 'google-calendar';

  const loadConnection = useCallback(async () => {
    if (!id) return;
    try {
      const list = await fetchIntegrations();
      const providerKey = id.replace('-', '_');
      // ICS subscriptions (provider='ics') also serve calendar cards, e.g.
      // outlook-calendar subscribed via ICS URL. Match by provider_display.
      const found = list.find(c =>
        c.provider === providerKey ||
        (c.provider === 'ics' && (c.provider_display || '').toLowerCase() === integration?.name.toLowerCase())
      );
      setConnection(found || null);
    } catch { /* no connections */ }
    setLoading(false);
  }, [id, integration]);

  useEffect(() => { loadConnection(); }, [loadConnection]);

  // Load the user's Google calendars once connected (keyed on connection id,
  // NOT the whole connection object — saving a selection updates config and
  // must not re-trigger this effect, otherwise the picker flashes to loading).
  useEffect(() => {
    if (!isGoogleCal || !connection) return;
    let cancelled = false;
    (async () => {
      setCalLoading(true);
      setCalError(null);
      try {
        const list = await fetchGoogleCalendars();
        if (cancelled) return;
        setCalendars(list);
        const cfg = (connection.config || {}) as Record<string, unknown>;
        // New format: calendar_ids list → legacy calendar_id string → default primary only
        let current: string[] = [];
        if (Array.isArray(cfg.calendar_ids) && (cfg.calendar_ids as string[]).length > 0) {
          current = (cfg.calendar_ids as string[]).filter((c) => list.some((x) => x.id === c));
        } else if (typeof cfg.calendar_id === 'string' && cfg.calendar_id) {
          current = list.some((c) => c.id === cfg.calendar_id) ? [cfg.calendar_id as string] : [];
        }
        if (current.length === 0) {
          const primary = list.find((c) => c.primary);
          current = primary ? [primary.id] : (list[0] ? [list[0].id] : []);
        }
        setSelectedCalIds(current);
      } catch (e: any) {
        if (!cancelled) setCalError(e?.message || 'Failed to load calendars');
      } finally {
        if (!cancelled) setCalLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGoogleCal, connection?.id]);

  const saveCalSelection = async (ids: string[]) => {
    setCalSaving(true);
    setCalSaved(false);
    setCalError(null);
    const names: Record<string, string> = {};
    for (const c of calendars) names[c.id] = c.summary;
    try {
      await saveGoogleCalendarSetting(ids, names);
      // Trigger an immediate sync so the /calendar page reflects the new
      // selection right away (no waiting for the 15-min interval).
      if (connection?.id) {
        try { await syncIntegrationNow(connection.id); } catch { /* sync errors surface on next interval */ }
      }
      setCalSaved(true);
      setConnection((prev) => prev ? { ...prev, config: { ...prev.config, calendar_ids: ids, calendar_names: names } } : prev);
    } catch (e: any) {
      setCalError(e?.message || 'Failed to save selection');
    } finally {
      setCalSaving(false);
    }
  };

  const handleToggleCal = (calId: string) => {
    const next = selectedCalIds.includes(calId)
      ? selectedCalIds.filter((c) => c !== calId)
      : [...selectedCalIds, calId];
    setSelectedCalIds(next);
    saveCalSelection(next);
  };

  const handleToggleAll = () => {
    const next = selectedCalIds.length === calendars.length
      ? []
      : calendars.map((c) => c.id);
    setSelectedCalIds(next);
    saveCalSelection(next);
  };

  // Listen for OAuth popup completion
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'nexus-oauth-complete') {
        setShowDialog(false);
        loadConnection();
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [loadConnection]);

  if (!integration) {
    return (
      <div className="mkt-detail">
        <div className="mkt-empty">
          <p>Integration not found</p>
          <Link to="/marketplace" style={{ color: 'var(--color-primary)', fontSize: 14 }}>
            ← Back to Marketplace
          </Link>
        </div>
      </div>
    );
  }

  const isConnected = !!connection;

  const handleDisconnect = async () => {
    if (!connection) return;
    try {
      await disconnectIntegration(connection.id);
      setConnection(null);
    } catch (err) {
      console.error('Disconnect failed', err);
    }
  };

  const handleConnected = () => {
    setShowDialog(false);
    loadConnection();
  };

  const statusColor = isConnected ? '#22c55e' : '#a0aec0';
  const statusText = isConnected ? 'Active' : loading ? 'Checking...' : 'Not connected';
  const lastSync = connection?.last_sync_at
    ? new Date(connection.last_sync_at).toLocaleString()
    : null;

  // Badge for connection method
  const methodLabel = integration.connectionMethod === 'oauth' ? 'One-click OAuth'
    : integration.connectionMethod === 'url' ? 'Paste URL'
    : integration.connectionMethod === 'webhook' ? 'Webhook'
    : 'Coming soon';

  return (
    <div className="mkt-detail">
      <div className="mkt-detail-breadcrumb">
        <Link to="/marketplace">Marketplace</Link>
        <span>›</span>
        <span>{integration.type}</span>
        <span>›</span>
        <span>{integration.name}</span>
      </div>

      <div className="mkt-detail-header">
        <div className="mkt-detail-icon" style={{ background: integration.color }}>
          {integration.icon}
        </div>
        <div className="mkt-detail-title">
          <h1>{integration.name}</h1>
          <span className="mkt-card-type" style={{ display: 'inline-block' }}>
            {integration.typeIcon} {integration.type}
            <span style={{
              marginLeft: 8, fontSize: 11, padding: '2px 8px', borderRadius: 10,
              background: 'var(--color-surface)', border: '1px solid var(--color-divider)',
              verticalAlign: 'middle',
            }}>
              {methodLabel}
            </span>
          </span>
          <div className="mkt-detail-meta">
            <span>{'★'.repeat(integration.popularity)}{'☆'.repeat(5 - integration.popularity)}</span>
            <span>{integration.connectionCount.toLocaleString()} connections</span>
          </div>
        </div>
        <div className="mkt-detail-action">
          {integration.connectionMethod === 'coming' ? (
            <button className="mkt-detail-btn" disabled style={{ opacity: 0.5 }}>
              Coming Soon
            </button>
          ) : isConnected ? (
            <button className="mkt-detail-btn connected" onClick={handleDisconnect}>
              Connected ✓
            </button>
          ) : (
            <button className="mkt-detail-btn connect" onClick={() => setShowDialog(true)}>
              Connect
            </button>
          )}
        </div>
      </div>

      <div className="mkt-detail-section">
        <h2>About this integration</h2>
        <p>{integration.longDesc}</p>
      </div>

      <div className="mkt-detail-section">
        <h2>How it works</h2>
        <p>{integration.howItWorks}</p>
      </div>

      <div className="mkt-detail-section">
        <h2>Key features</h2>
        <div className="mkt-detail-features">
          {integration.features.map((feat, i) => (
            <div key={i} className="mkt-detail-feat">
              <SvcIcon name="check" />
              <span>{feat}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mkt-detail-section">
        <h2>Connection status</h2>
        <div className="mkt-detail-status">
          <span className="dot" style={{ background: statusColor }} />
          <span>
            {statusText}
            {isConnected && (
              <span style={{ fontSize: 13, color: 'var(--color-text-muted)', marginLeft: 8 }}>
                — {integration.name} is connected to your account
              </span>
            )}
          </span>
        </div>
        {lastSync && (
          <div className="mkt-detail-status" style={{ marginTop: 8 }}>
            <SvcIcon name="refresh-cw" size={14} style={{ marginRight: 8, color: 'var(--color-text-muted)' }} />
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              Last synced: {lastSync}
            </span>
          </div>
        )}
        {connection?.status === 'error' && (
          <div className="mkt-detail-status" style={{ color: '#ef4444', marginTop: 8 }}>
            <SvcIcon name="alert-circle" size={14} style={{ marginRight: 8 }} />
            <span>Connection error — re-connect or check provider status</span>
          </div>
        )}
      </div>

      {/* Google Calendar picker — choose which calendars to sync (multi-select) */}
      {isGoogleCal && isConnected && (
        <div className="mkt-detail-section">
          <h2>Sync calendars</h2>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '4px 0 14px' }}>
            Pick which Google Calendars to mirror into Penguin CRM. Default: primary only. Events sync within 15 minutes of a change.
          </p>

          {calLoading ? (
            <div className="mkt-detail-status" style={{ color: 'var(--color-text-muted)' }}>
              <SvcIcon name="refresh-cw" size={14} className="spin" style={{ marginRight: 8 }} />
              <span>Loading your calendars…</span>
            </div>
          ) : (
            <>
              <div className="gcal-picker-header">
                <span className="gcal-count">
                  {selectedCalIds.length} of {calendars.length} selected
                </span>
                <button
                  className="gcal-toggle-all"
                  onClick={handleToggleAll}
                  disabled={calSaving}
                >
                  {selectedCalIds.length === calendars.length ? 'Clear all' : 'Select all'}
                </button>
              </div>

              <div className="gcal-list">
                {calendars.length === 0 && (
                  <div style={{ fontSize: 13, color: 'var(--color-text-faint)' }}>No calendars found</div>
                )}
                {calendars.map((c) => {
                  const checked = selectedCalIds.includes(c.id);
                  return (
                    <label key={c.id} className={`gcal-item${checked ? ' checked' : ''}`}>
                      <input
                        type="checkbox"
                        className="gcal-checkbox"
                        checked={checked}
                        disabled={calSaving}
                        onChange={() => handleToggleCal(c.id)}
                      />
                      <span className="gcal-item-name">{c.summary}</span>
                      {c.primary && <span className="gcal-item-badge">Primary</span>}
                    </label>
                  );
                })}
              </div>

              <div style={{ marginTop: 10, fontSize: 12.5, minHeight: 18 }}>
                {calSaving && <span style={{ color: 'var(--color-text-muted)' }}>Saving…</span>}
                {calSaved && !calSaving && (
                  <span style={{ color: 'var(--color-success)' }}>
                    <SvcIcon name="check" size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
                    Calendars updated & synced — check the Calendar page
                  </span>
                )}
                {calError && <span style={{ color: '#ef4444' }}>{calError}</span>}
              </div>
            </>
          )}
        </div>
      )}

      {/* Connect Dialog */}
      {showDialog && (
        <ConnectDialog
          integration={integration}
          onClose={() => setShowDialog(false)}
          onConnected={handleConnected}
        />
      )}
    </div>
  );
}
