import { useState, useMemo, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';
import { availableIntegrations as integrations, integrationTypes } from '../data/integrations';
import { fetchIntegrations, disconnectIntegration } from '../lib/integration-api';
import type { IntegrationRecord } from '../lib/integration-api';
import ConnectDialog from '../components/ConnectDialog';

type ConnectionMap = Record<string, IntegrationRecord>;

export default function MarketplacePage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [activeType, setActiveType] = useState('All');
  const [connections, setConnections] = useState<ConnectionMap>({});
  const [loading, setLoading] = useState(true);
  const [dialogIntegration, setDialogIntegration] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await fetchIntegrations();
      const map: ConnectionMap = {};
      list.forEach(c => { map[c.provider] = c; });
      setConnections(map);
    } catch { /* not logged in */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Listen for OAuth popup messages
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'nexus-oauth-complete') {
        load();
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [load]);

  const filtered = useMemo(() => {
    return integrations
      .filter(i => {
        const matchSearch =
          !search ||
          i.name.toLowerCase().includes(search.toLowerCase()) ||
          i.shortDesc.toLowerCase().includes(search.toLowerCase());
        const matchType = activeType === 'All' || i.type === activeType;
        return matchSearch && matchType;
      })
      .map(i => {
        // Card is connected if a connection matches by provider key (e.g.
        // outlook_calendar, google_calendar) OR any ICS subscription whose
        // display name matches this integration. This is generic across
        // tenants — ICS URL subscriptions serve their matching calendar card.
        const providerKey = i.id.replace('-', '_');
        const direct = connections[providerKey];
        const icsMatch = !direct
          ? Object.values(connections).find(c =>
              c.provider === 'ics' &&
              (c.provider_display || '').toLowerCase() === i.name.toLowerCase()
            )
          : undefined;
        return {
          ...i,
          isConnected: !!direct || !!icsMatch,
          _connection: icsMatch || direct,
        };
      });
  }, [search, activeType, connections]);

  const renderStars = (n: number) =>
    Array.from({ length: 5 }, (_, i) => (
      <span key={i} className={i < n ? 'filled' : ''}>★</span>
    ));

  const handleConnectClick = (e: React.MouseEvent, int: typeof filtered[0]) => {
    e.stopPropagation();
    if (int.connectionMethod === 'coming') return;
    if (int.connectionMethod === 'oauth') return; // OAuth handled in detail page
    setDialogIntegration(int.id);
  };

  const handleDisconnect = async (e: React.MouseEvent, providerKey: string) => {
    e.stopPropagation();
    const record = connections[providerKey];
    if (!record) return;
    try {
      await disconnectIntegration(record.id);
      setConnections(prev => {
        const next = { ...prev };
        delete next[providerKey];
        return next;
      });
    } catch (err) {
      console.error('Disconnect failed', err);
    }
  };

  const dialogInt = dialogIntegration ? integrations.find(i => i.id === dialogIntegration) : null;

  return (
    <div className="mkt-page">
      <div className="mkt-search-wrap">
        <div className="mkt-search">
          <SvcIcon name="search" size={18} />
          <input
            type="text"
            placeholder="Search integrations..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            autoFocus
          />
        </div>
      </div>

      <div className="mkt-filters">
        <button
          className={`mkt-filter${activeType === 'All' ? ' active' : ''}`}
          onClick={() => setActiveType('All')}
        >All</button>
        {integrationTypes.map(type => (
          <button
            key={type}
            className={`mkt-filter${activeType === type ? ' active' : ''}`}
            onClick={() => setActiveType(type)}
          >{type}</button>
        ))}
      </div>

      {loading ? (
        <div className="mkt-empty"><p>Loading integrations...</p></div>
      ) : filtered.length === 0 ? (
        <div className="mkt-empty">
          <SvcIcon name="package-open" />
          <p>No integrations found</p>
        </div>
      ) : (
        <div className="mkt-grid">
          {filtered.map(int => {
            const providerKey = int.id.replace('-', '_');
            const isConnected = int.isConnected;
            return (
              <div
                key={int.id}
                className="mkt-card"
                onClick={() => navigate(`/marketplace/${int.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={e => {
                  if (e.key === 'Enter') navigate(`/marketplace/${int.id}`);
                }}
              >
                <div className="mkt-card-top">
                  <div className="mkt-card-icon" style={{ background: int.color }}>
                    {int.icon}
                  </div>
                  <div className="mkt-card-info">
                    <div className="mkt-card-name">
                      {int.name}
                      <span className="mkt-card-type">{int.type}</span>
                    </div>
                    <div className="mkt-card-desc">{int.shortDesc}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-faint)', marginTop: 4 }}>
                      {int.connectionMethod === 'url' && '📋 Paste URL'}
                      {int.connectionMethod === 'webhook' && '🔗 Webhook'}
                      {int.connectionMethod === 'oauth' && '🔑 One-click OAuth'}
                      {int.connectionMethod === 'coming' && '🚧 Coming soon'}
                    </div>
                  </div>
                </div>
                <div className="mkt-card-bottom">
                  <div className="mkt-stars">
                    {renderStars(int.popularity)}
                    <span>({int.connectionCount.toLocaleString()})</span>
                  </div>
                  {int.connectionMethod === 'coming' ? (
                    <button className="mkt-card-btn" disabled style={{ opacity: 0.5 }}>Soon</button>
                  ) : isConnected ? (
                    <button
                      className="mkt-card-btn connected"
                      onClick={e => handleDisconnect(e, providerKey)}
                    >Connected ✓</button>
                  ) : (
                    <button
                      className="mkt-card-btn connect"
                      onClick={e => handleConnectClick(e, int)}
                    >Connect</button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Connect Dialog */}
      {dialogInt && (
        <ConnectDialog
          integration={dialogInt}
          onClose={() => setDialogIntegration(null)}
          onConnected={() => { setDialogIntegration(null); load(); }}
        />
      )}
    </div>
  );
}
