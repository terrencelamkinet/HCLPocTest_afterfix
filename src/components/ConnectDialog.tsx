import { useState } from 'react';
import SvcIcon from '../components/SvcIcon';
import { isSafeExternalUrl, safeExternalUrl } from '../lib/safeUrl';
import { useEscapeKey } from '../lib/useEscapeKey';
import type { Integration } from '../data/integrations';

interface Props {
  integration: Integration;
  onClose: () => void;
  onConnected: () => void;
}

export default function ConnectDialog({ integration, onClose, onConnected }: Props) {
  useEscapeKey(onClose);
  const [url, setUrl] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  // WhatsApp specific
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [waPending, setWaPending] = useState(false);
  const [icsMode, setIcsMode] = useState(false);  // google-calendar: ICS URL fallback
  const isWhatsApp = integration.id === 'whatsapp';
  const supportsIcs = integration.id === 'google-calendar' || integration.id === 'outlook-calendar';

  // Generate a fake webhook URL for webhook-based integrations
  const webhookUrl = `${window.location.origin}/api/v1/webhooks/${integration.id}/${Date.now().toString(36)}`;

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* fallback */ }
  };

  const handleSendOtp = async () => {
    if (!phone.trim()) {
      setError('Please enter your phone number');
      return;
    }
    setWaPending(true);
    setError('');
    try {
      // 2026-09-15 SAST：session 喺 httpOnly cookie（唔再讀 localStorage 拎 token）
      const res = await fetch('/api/v1/whatsapp/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ phone: phone.trim() }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody?.detail || 'Failed to send OTP');
      }
      const data = await res.json();
      setOtpSent(true);
      // Debug/test mode: auto-fill OTP if returned by API
      if (data.otp) {
        setOtp(data.otp);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to send OTP');
    }
    setWaPending(false);
  };

  const handleVerifyOtp = async () => {
    if (!otp.trim()) {
      setError('Please enter the verification code');
      return;
    }
    setConnecting(true);
    setError('');
    try {
      // 2026-09-15 SAST：session 喺 httpOnly cookie
      const res = await fetch('/api/v1/whatsapp/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ phone: phone.trim(), otp: otp.trim() }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody?.detail || 'Verification failed');
      }
      onConnected();
    } catch (err: any) {
      setError(err?.message || 'Verification failed');
    }
    setConnecting(false);
  };

  const handleConnect = async () => {
    if (!url.trim()) {
      setError('Please paste your connection URL or key');
      return;
    }
    setConnecting(true);
    setError('');

    try {
      const res = await fetch('/api/v1/integrations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          provider: integration.id.replace('-', '_'),
          provider_display: integration.name,
          status: 'active',
          config: { connection_url: url.trim() },
          metadata_: { connected_at: new Date().toISOString() },
        }),
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody?.detail || 'Connection failed');
      }

      onConnected();
    } catch (err: any) {
      setError(err?.message || 'Failed to connect');
    }
    setConnecting(false);
  };

  const handleOAuthConnect = () => {
    // OAuth popup flow — opens Google/Microsoft login
    fetch('/api/v1/integrations/oauth/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ provider: integration.id.replace('-', '_'), origin: window.location.origin }),
    }).then(r => r.json()).then(data => {
      if (data.oauth_url && isSafeExternalUrl(data.oauth_url)) {
        // 2026-09-15 SAST：oauth_url 由 server 回傳 → 只准 http(s)，並加 noopener,noreferrer
        const w = 600, h = 700;
        const left = window.screenX + (window.outerWidth - w) / 2;
        const top = window.screenY + (window.outerHeight - h) / 2;
        window.open(safeExternalUrl(data.oauth_url) as string, 'nexus-oauth',
          `width=${w},height=${h},left=${left},top=${top},popup=1,noopener,noreferrer`);
        window.addEventListener('message', function handler(e) {
          if (e.data?.type === 'nexus-oauth-complete') {
            window.removeEventListener('message', handler);
            onConnected();
          }
        });
      }
    }).catch(err => setError(err?.message || 'Failed to start OAuth'));
  };

  const handleIcsConnect = async () => {
    // ICS URL subscription — google-calendar fallback (public calendars)
    if (!url.trim()) {
      setError('Please paste your ICS calendar URL');
      return;
    }
    setConnecting(true);
    setError('');
    try {
      const authRaw = localStorage.getItem('nexus_crm_auth');
      if (!authRaw) { setError('Not signed in'); setConnecting(false); return; }
      const auth = JSON.parse(authRaw);
      const res = await fetch('/api/v1/integrations/ics', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${auth.access_token}`,
        },
        body: JSON.stringify({ ics_url: url.trim(), provider_display: integration.name }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody?.detail || 'Connection failed');
      }
      onConnected();
    } catch (err: any) {
      setError(err?.message || 'Failed to connect');
    }
    setConnecting(false);
  };

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-box" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
        {/* Header */}
        <div className="dialog-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div className="mkt-card-icon" style={{ background: integration.color, width: 36, height: 36, fontSize: 14 }}>
              {integration.icon}
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: 16 }}>Connect {integration.name}</h3>
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{integration.typeIcon} {integration.type}</span>
            </div>
          </div>
          <button className="dialog-close" onClick={onClose}><SvcIcon name="x" size={18} /></button>
        </div>

        {/* Body */}
        <div className="dialog-body" style={{ padding: '20px 24px' }}>
          {integration.connectionMethod === 'coming' && (
            <div style={{ textAlign: 'center', padding: 24 }}>
              <p style={{ fontSize: 16, margin: '0 0 8px' }}>🚧 Coming Soon</p>
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                {integration.name} integration is under development. We'll notify you when it's ready.
              </p>
            </div>
          )}

          {integration.connectionMethod === 'webhook' && (
            <>
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 16px' }}>
                Use this webhook URL in {integration.name} to send data to Penguin:
              </p>
              <div className="mkt-url-row">
                <code className="mkt-url-display">{webhookUrl}</code>
                <button className="mkt-copy-btn" onClick={() => handleCopy(webhookUrl)}>
                  {copied ? <SvcIcon name="check" size={16} /> : <SvcIcon name="copy" size={16} />}
                </button>
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 12, lineHeight: 1.5 }}>
                {integration.howItWorks}
              </p>
            </>
          )}

          {integration.connectionMethod === 'url' && !isWhatsApp && (
            <>
              <div className="mkt-steps">
                {integration.connectSteps?.map((step, i) => (
                  <div key={i} className="mkt-step">
                    <span className="mkt-step-num">{i + 1}</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 16 }}>
                <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 6 }}>Paste your connection URL or key</label>
                <input
                  className="mkt-url-input"
                  type="text"
                  placeholder={integration.connectPlaceholder || 'Paste URL here...'}
                  value={url}
                  onChange={e => { setUrl(e.target.value); setError(''); }}
                  autoFocus
                />
              </div>
              {error && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{error}</p>}
            </>
          )}

          {isWhatsApp && (
            <>
              <div className="mkt-steps">
                <div className="mkt-step">
                  <span className="mkt-step-num">1</span>
                  <span>Enter your WhatsApp phone number</span>
                </div>
                <div className="mkt-step">
                  <span className="mkt-step-num">2</span>
                  <span>Receive OTP via WhatsApp</span>
                </div>
                <div className="mkt-step">
                  <span className="mkt-step-num">3</span>
                  <span>Enter code to complete binding</span>
                </div>
              </div>

              {!otpSent ? (
                <div style={{ marginTop: 16 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 6 }}>WhatsApp Phone Number</label>
                  <input
                    className="mkt-url-input"
                    type="tel"
                    placeholder="+852 9876 5432"
                    value={phone}
                    onChange={e => { setPhone(e.target.value); setError(''); }}
                    autoFocus
                  />
                  {error && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{error}</p>}
                  <button
                    className="mkt-card-btn connect"
                    onClick={handleSendOtp}
                    disabled={waPending}
                    style={{ marginTop: 12, width: '100%' }}
                  >
                    {waPending ? 'Sending OTP...' : 'Send Verification Code'}
                  </button>
                </div>
              ) : (
                <div style={{ marginTop: 16 }}>
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12 }}>
                    A 6-digit code has been sent to <strong>{phone}</strong> via WhatsApp. Enter it below.
                  </p>
                  <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 6 }}>Verification Code</label>
                  <input
                    className="mkt-url-input"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    value={otp}
                    onChange={e => { setOtp(e.target.value.replace(/\D/g, '').slice(0, 6)); setError(''); }}
                    autoFocus
                  />
                  {error && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{error}</p>}
                  <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                    <button
                      className="mkt-card-btn"
                      onClick={() => { setOtpSent(false); setOtp(''); setPhone(''); setError(''); }}
                      style={{ flex: 1, background: 'none', border: '1px solid var(--border-color)' }}
                    >
                      Change Number
                    </button>
                    <button
                      className="mkt-card-btn connect"
                      onClick={handleVerifyOtp}
                      disabled={connecting || otp.length < 6}
                      style={{ flex: 1 }}
                    >
                      {connecting ? 'Verifying...' : 'Verify & Connect'}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {integration.connectionMethod === 'oauth' && (
            !icsMode ? (
              <div style={{ textAlign: 'center', padding: 12 }}>
                <p style={{ fontSize: 14, marginBottom: 12 }}>
                  Click Connect to authorize Penguin via {integration.name}
                </p>
                <p style={{ fontSize: 12, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
                  {integration.howItWorks}
                </p>
                {supportsIcs && (
                  <button
                    className="mkt-card-btn"
                    onClick={() => { setIcsMode(true); setError(''); }}
                    style={{ marginTop: 16, background: 'none', border: '1px solid var(--border-color)' }}
                  >
                    Or paste an ICS calendar link instead
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="mkt-steps">
                  {integration.connectSteps?.map((step, i) => (
                    <div key={i} className="mkt-step">
                      <span className="mkt-step-num">{i + 1}</span>
                      <span>{step}</span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 16 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 6 }}>Paste your ICS calendar URL</label>
                  <input
                    className="mkt-url-input"
                    type="text"
                    placeholder={integration.connectPlaceholder || 'https://.../basic.ics'}
                    value={url}
                    onChange={e => { setUrl(e.target.value); setError(''); }}
                    autoFocus
                  />
                </div>
                {error && <p style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{error}</p>}
                <button
                  className="mkt-card-btn"
                  onClick={() => { setIcsMode(false); setUrl(''); setError(''); }}
                  style={{ marginTop: 12, background: 'none', border: '1px solid var(--border-color)' }}
                >
                  ← Back to Google sign-in
                </button>
              </>
            )
          )}
        </div>

        {/* Footer */}
        <div className="dialog-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 24px' }}>
          <button className="mkt-card-btn" onClick={onClose} style={{ background: 'none', border: '1px solid var(--border-color)' }}>
            Cancel
          </button>
          {integration.connectionMethod === 'url' && !isWhatsApp && (
            <button className="mkt-card-btn connect" onClick={handleConnect} disabled={connecting}>
              {connecting ? 'Connecting...' : 'Connect'}
            </button>
          )}
          {integration.connectionMethod === 'oauth' && !icsMode && (
            <button className="mkt-card-btn connect" onClick={handleOAuthConnect}>
              {integration.oauthLabel || `Authorize with ${integration.name}`}
            </button>
          )}
          {integration.connectionMethod === 'oauth' && icsMode && (
            <button className="mkt-card-btn connect" onClick={handleIcsConnect} disabled={connecting}>
              {connecting ? 'Connecting...' : 'Connect ICS Calendar'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
