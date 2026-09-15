import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import SvcIcon from '../components/SvcIcon';

const API_BASE = '';

export default function OAuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<'processing' | 'success' | 'error'>('processing');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');

    if (!code || !state) {
      setStatus('error');
      setErrorMsg('Missing authorization code or state parameter.');
      return;
    }

    (async () => {
      try {
        // 2026-09-15 SAST：session 喺 httpOnly cookie（唔再讀 localStorage token）。
        // 冇 cookie 時 backend 會回 401，下面 catch 會顯示請重新登入。
        const res = await fetch(`${API_BASE}/api/v1/integrations/oauth/callback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ code, state }),
        });

        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}));
          throw new Error(errBody?.detail || `HTTP ${res.status}`);
        }

        const result = await res.json();
        setStatus('success');

        // Post message to opener (main window)
        if (window.opener && !window.opener.closed) {
          window.opener.postMessage({
            type: 'nexus-oauth-complete',
            provider: result?.provider || '',
            success: true,
          }, window.location.origin);
        }

        // Auto-close after 1.5s
        setTimeout(() => window.close(), 1500);
      } catch (err: any) {
        setStatus('error');
        setErrorMsg(err?.message || 'Failed to complete OAuth connection.');
      }
    })();
  }, [searchParams]);

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      background: 'var(--bg-body)',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      color: 'var(--color-text)',
    }}>
      <div style={{ textAlign: 'center', maxWidth: 400, padding: 40 }}>
        {status === 'processing' && (
          <>
            <SvcIcon name="loader" size={48} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 20px', color: 'var(--color-primary)' }} />
            <h2 style={{ margin: '0 0 8px', fontSize: 20 }}>Connecting...</h2>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              Completing your connection. This window will close automatically.
            </p>
          </>
        )}

        {status === 'success' && (
          <>
            <SvcIcon name="check-circle" size={48} style={{ color: '#22c55e', margin: '0 auto 20px' }} />
            <h2 style={{ margin: '0 0 8px', fontSize: 20 }}>Connected!</h2>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              Your integration is now active. This window will close shortly.
            </p>
          </>
        )}

        {status === 'error' && (
          <>
            <SvcIcon name="x-circle" size={48} style={{ color: '#ef4444', margin: '0 auto 20px' }} />
            <h2 style={{ margin: '0 0 8px', fontSize: 20 }}>Connection failed</h2>
            <p style={{ color: '#ef4444', fontSize: 14 }}>{errorMsg}</p>
            <button
              onClick={() => window.close()}
              style={{
                marginTop: 16,
                padding: '8px 24px',
                background: 'var(--color-primary)',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >Close window</button>
          </>
        )}
      </div>
    </div>
  );
}
