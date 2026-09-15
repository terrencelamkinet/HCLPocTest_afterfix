import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../lib/AuthContext';
import { signup, forgotPassword, resetPassword, storeSession, apiClient } from '../lib/api';

export default function LoginPage() {
  const { t } = useTranslation();
  const { login, verifyMfa, sendMfaCode, mfaEmail, refreshMe } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [step, setStep] = useState<'login' | 'mfa' | 'register' | 'forgot' | 'reset'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  // 登入成功後、authed tree 首次 render 會阻塞主線程 1 秒以上（見
  // docs/bug-mobile-nav-first-load.md）。主線程一封鎖就冇得 repaint，所以
  // 要喺 navigate 之前用 flushSync 強制畫好呢個 overlay，令用戶見到嘅
  // 最後一格係「登入中…」而唔係一個就快消失、但睇落可以用嘅登入頁。
  // 唔可以重用 loading：handleLogin 嘅 finally 會喺 block 之前清掉佢。
  const [redirecting, setRedirecting] = useState(false);
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const otpRefs = useRef<(HTMLInputElement | null)[]>([]);

  // ── Google Sign-In (GIS ID-token flow, 2026-09-11) ────────────────────────
  // The client ID is PUBLIC — Google requires it in the browser — so shipping it
  // is fine. There is no client SECRET anywhere: the backend verifies Google's
  // signed ID token instead of exchanging an authorisation code.
  const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined)
    || '678301436253-nhu9mtk08p8eq2fhutqfjkn1jl48rpnt.apps.googleusercontent.com';
  const googleBtnRef = useRef<HTMLDivElement | null>(null);

  const handleGoogleCredential = async (resp: { credential?: string }) => {
    if (!resp?.credential) return;
    setError('');
    setLoading(true);
    try {
      const res = await apiClient.post('/api/v1/auth/google', {
        credential: resp.credential,
        // Google's ID token carries no timezone, so report the browser's own
        // (e.g. Asia/Hong_Kong). The backend only uses it to fill a blank.
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
      });
      // 2026-09-15 SAST：cookie 已經由 server 種（HttpOnly），前端只記 hint
      storeSession(res.email || '');
      await refreshMe();
      setRedirecting(true);
      setTimeout(() => navigate('/dashboard', { replace: true }), 50);
    } catch (err: any) {
      // The backend refuses an unknown Google email (403) and a credential that
      // does not verify (401); surface its message rather than inventing one.
      setError(err?.detail || err?.message || t('login.errorLogin'));
    } finally {
      setLoading(false);
    }
  };

  // Load Google Identity Services once and render its button. Only on the login
  // step: the MFA/register/forgot screens must not offer a second way in.
  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || step !== 'login') return;
    const w = window as any;
    let cancelled = false;
    const render = () => {
      if (cancelled || !w.google?.accounts?.id || !googleBtnRef.current) return;
      w.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleCredential,
        // 2026-09-11: force the classic popup. The library's FedCM button can fall
        // back to the *redirect* UX, which needs a registered redirect URI — and
        // that surfaced as "Error 400: redirect_uri_mismatch" on penguincrm.io.
        // An ID-token flow should never leave the page, so pin it to popup.
        ux_mode: 'popup',
        use_fedcm_for_button: false,
      });
      w.google.accounts.id.renderButton(googleBtnRef.current, {
        theme: 'outline', size: 'large', width: 320,
        text: 'continue_with', logo_alignment: 'center',
      });
    };
    if (w.google?.accounts?.id) { render(); return; }
    let s = document.getElementById('gsi-client') as HTMLScriptElement | null;
    if (!s) {
      s = document.createElement('script');
      s.id = 'gsi-client';
      s.src = 'https://accounts.google.com/gsi/client';
      s.async = true;
      s.defer = true;
      document.head.appendChild(s);
    }
    s.addEventListener('load', render);
    return () => { cancelled = true; s?.removeEventListener('load', render); };
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  // Detect reset_token from URL
  const resetToken = searchParams.get('reset_token');
  useEffect(() => {
    if (resetToken) {
      setStep('reset');
    }
  }, [resetToken]);

  useEffect(() => {
    // Google OAuth return: /login/#google_ok=1
    //   2026-09-15 SAST：token 已經唔再放喺 URL fragment（原本 #google_token=... 會
    //   落入 history／分享／DevTools，再被前端寫入 localStorage）。而家 session 喺
    //   httpOnly cookie（見 backend google_callback），URL 只帶一個 ok 標記。
    // Special access link: /login/#sa=<token>（GG family debug 通道，2026-08-31）
    const params = new URLSearchParams(location.hash.replace(/^#/, ''));
    const googleOk = params.get('google_ok');
    const saToken = params.get('sa');
    if (googleOk) {
      (async () => {
        try {
          const me = await apiClient.get('/api/v1/auth/me');
          if (me?.email) storeSession(me.email);
        } catch {
          /* 下面 refreshMe() 會反映真實狀態 */
        }
        await refreshMe();
        setRedirecting(true);
        setTimeout(() => navigate('/dashboard', { replace: true }), 50);
      })();
    } else if (saToken) {
      // Exchange special access token for a normal session (no MFA)
      apiClient.post('/api/v1/auth/special-access/verify', { token: saToken })
        .then(async (res: any) => {
          storeSession(res?.email || '');
          await refreshMe();
          setRedirecting(true);
      setTimeout(() => navigate('/dashboard', { replace: true }), 50);
        })
        .catch(() => {
          // 過期 / revoke — fallback 正常登入
          location.hash = '';
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // 2026-09-12（用戶回報：desktop 見到 items 背景變黑）
    // 之前呢度跟 OS 深色偏好（prefers-color-scheme）自動切 dark theme →
    // 桌面 OS 開深色嘅用戶一登入就成個 app 變黑（--color-surface #fff → #1a1d23），
    // 而手機 OS 淺色就正常 → 造成「只有 desktop 出事」。
    // 改為：只用用戶自己儲存過嘅選擇（nexus-theme），否則預設淺色。
    // 想手動轉深色照樣可以用 header 嘅 toggle（會寫入 nexus-theme）。
    try {
      const saved = localStorage.getItem('nexus-theme');
      const t = saved === 'dark' ? 'dark' : 'light';
      setTheme(t);
      document.documentElement.setAttribute('data-theme', t);
    } catch {
      /* ignore */
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.setAttribute('data-theme', next);
  };

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await login(email, password);
      if (result === 'success') {
        setRedirecting(true);
        // 一定要讓出一個 frame 先 navigate：flushSync 只係 commit DOM，
        // 瀏覽器要等 JS task 完結先可以 paint。如果唔讓，overlay 會同
        // authed tree 同一格先出現 = 完全冇用（實測 overlay 1492ms / nav 1610ms）。
        await new Promise((r) => setTimeout(r, 50));
        navigate('/dashboard', { replace: true });
      } else {
        setStep('mfa');
        setTimeout(() => otpRefs.current[0]?.focus(), 100);
      }
    } catch (err: any) {
      setError(err?.detail || err?.message || t('login.errorLogin'));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError(t('login.errorPasswordMismatch'));
      return;
    }
    if (password.length < 6) {
      setError(t('login.errorPasswordShort'));
      return;
    }
    setLoading(true);
    try {
      const res = await signup(email, password, displayName);
      // 2026-09-15 SAST：session 喺 httpOnly cookie（register 已經種）
      storeSession(res.email || email);
      await refreshMe();
      setRedirecting(true);
      setTimeout(() => navigate('/dashboard', { replace: true }), 50);
    } catch (err: any) {
      setError(err?.detail || err?.message || t('login.errorRegister'));
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      const res = await forgotPassword(email);
      setSuccess(res.message || t('login.resetSent'));
    } catch (err: any) {
      setError(err?.detail || err?.message || t('login.errorSendReset'));
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError(t('login.errorPasswordMismatch'));
      return;
    }
    if (password.length < 6) {
      setError(t('login.errorPasswordShort'));
      return;
    }
    if (!resetToken) {
      setError(t('login.errorInvalidToken'));
      return;
    }
    setLoading(true);
    try {
      await resetPassword(resetToken, password);
      setSuccess(t('login.resetSuccess'));
      setTimeout(() => {
        setStep('login');
        setSuccess('');
      }, 2000);
    } catch (err: any) {
      setError(err?.detail || err?.message || t('login.errorResetFailed'));
    } finally {
      setLoading(false);
    }
  };

  const goTo = (s: typeof step) => {
    setStep(s);
    setError('');
    setSuccess('');
    setPassword('');
    setConfirmPassword('');
    setDisplayName('');
  };

  const handleOtpChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const next = [...otp];
    next[index] = value.slice(-1);
    setOtp(next);
    if (value && index < 5) otpRefs.current[index + 1]?.focus();
    const code = next.join('');
    if (code.length === 6) handleVerifyMfa(code);
  };

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus();
    }
  };

  const handleVerifyMfa = async (code?: string) => {
    const otpCode = code || otp.join('');
    if (otpCode.length !== 6) return;
    setError('');
    setLoading(true);
    try {
      await verifyMfa(otpCode);
      setRedirecting(true);
      await new Promise((r) => setTimeout(r, 50));   // 讓出一個 frame 先，理由同上
      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || t('login.errorVerify'));
      setOtp(['', '', '', '', '', '']);
      otpRefs.current[0]?.focus();
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    try {
      await sendMfaCode();
      setSuccess(t('login.codeResent'));
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      setError(err?.detail || t('login.errorResend'));
    }
  };

  return (
    <div className="login-page">
      {/* 登入成功之後，authed tree 首次 render 會封鎖主線程約 1.2 秒（見
          docs/bug-mobile-nav-first-load.md）。主線程被封鎖期間瀏覽器冇得 repaint，
          所以呢個 overlay 必須喺阻塞開始之前就畫好 —— 由 flushSync 保證 ——
          令用戶見到嘅最後一格係「登入中…」，而唔係一個就快消失、但睇落可以用嘅登入頁。 */}
      {redirecting && (
        <div
          role="status"
          aria-live="polite"
          data-testid="login-redirecting"
          style={{
            position: 'fixed', inset: 0, zIndex: 9999, display: 'grid', placeItems: 'center',
            background: 'var(--surface-1, #fff)', color: 'var(--text-1, #333)', fontSize: 15,
          }}
        >
          {t('login.redirecting', { defaultValue: '登入中…' })}
        </div>
      )}
      <a className="skip-link" href="#authMain">Skip to content</a>
      <div className="app">
        {/* ── Brand pane ── */}
        <aside className="brand-pane">
          <div>
            <div className="brand-top">
              <div className="brand-mark" aria-label="Penguin logo">
                <img src="/assets/logo/logo_square.png" alt="PenguinCRM" className="brand-mark-img" />
                <span>{t('app.name')}</span>
              </div>
              <button className="theme-btn" onClick={toggleTheme} aria-label="Switch theme">
                {theme === 'dark' ? (
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="5"/>
                    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                  </svg>
                )}
              </button>
            </div>
            <div className="hero-copy">
              <div className="eyebrow">{t('login.eyebrow')}</div>
              <h1>{t('login.heroTitle')}</h1>
              <p>{t('login.heroSubtitle')}</p>
              <div className="mini-proof" aria-label="benefits">
                <div className="proof-card">
                  <div className="n">{t('login.proofGoogleTitle')}</div>
                  <div className="l">{t('login.proofGoogleDesc')}</div>
                </div>
                <div className="proof-card">
                  <div className="n">{t('login.proofLocalTitle')}</div>
                  <div className="l">{t('login.proofLocalDesc')}</div>
                </div>
                <div className="proof-card">
                  <div className="n">{t('login.proofRecoveryTitle')}</div>
                  <div className="l">{t('login.proofRecoveryDesc')}</div>
                </div>
              </div>
            </div>
          </div>
          <div className="brand-bottom">
            <span>{t('login.badgeJwt')}</span>
            <span>•</span>
            <span>{t('login.badgeMobile')}</span>
            <span>•</span>
            <span>{t('login.badgeWcag')}</span>
          </div>
        </aside>

        {/* ── Auth pane ── */}
        <main className="auth-pane" id="authMain">
          <div className="auth-shell">
            <section className="auth-card" aria-live="polite">
              <div className="auth-head">
                <h2 id="pageTitle">
                  {step === 'login' && t('login.title')}
                  {step === 'register' && t('login.createAccount')}
                  {step === 'forgot' && t('login.forgotPassword')}
                  {step === 'reset' && t('login.resetTitle')}
                  {step === 'mfa' && t('login.mfaTitle')}
                </h2>
                <p id="pageSubtitle">
                  {step === 'login' && t('login.subtitle')}
                  {step === 'register' && t('login.registerSubtitle')}
                  {step === 'forgot' && t('login.forgotSubtitle')}
                  {step === 'reset' && t('login.resetSubtitle')}
                  {step === 'mfa' && <>{t('login.mfaSentTo')} <strong>{mfaEmail}</strong>.</>}
                </p>
              </div>
              <div className="auth-body">

                {/* ──── LOGIN ──── */}
                {step === 'login' && (
                  <section className="page active" data-page="login">
                    <div className={`notice error ${error ? 'show' : ''}`}>{error}</div>
                    <div className={`notice success ${success ? 'show' : ''}`}>{success}</div>
                    {/* Google Sign-In. Google's own script renders the button into
                        this host, so its label follows the user's Google language.
                        This REPLACES the old /api/v1/auth/google/start button: that
                        was the authorisation-code redirect flow, which needs a
                        registered redirect URI and produced "Error 400:
                        redirect_uri_mismatch" on penguincrm.io. The ID-token flow
                        runs entirely in a popup and needs no redirect at all. */}
                    <div ref={googleBtnRef} style={{ display: 'flex', justifyContent: 'center' }} />
                    <div className="divider">{t('login.divider')}</div>
                    <form className="form" onSubmit={handleLogin} noValidate>
                      <div className="field">
                        <label htmlFor="loginEmail">{t('login.emailLabel')}</label>
                        <input
                          className="input"
                          id="loginEmail"
                          name="email"
                          type="email"
                          inputMode="email"
                          autoComplete="email"
                          placeholder={t('login.emailPlaceholder')}
                          value={email}
                          onChange={e => setEmail(e.target.value)}
                          required
                          autoFocus
                        />
                      </div>
                      <div className="field">
                        <div className="field-row">
                          <label htmlFor="loginPassword">{t('login.passwordLabel')}</label>
                        </div>
                        <div className="input-wrap">
                          <input
                            className="input"
                            id="loginPassword"
                            name="password"
                            type="password"
                            autoComplete="current-password"
                            placeholder={t('login.passwordPlaceholder')}
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            required
                          />
                        </div>
                      </div>
                      <div className="meta-row">
                        <label className="check">
                          <input type="checkbox" defaultChecked />
                          <span>{t('login.keepSignedIn')}</span>
                        </label>
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={loading}>
                        <span className="btn-label">
                          {loading ? <><span className="spinner"></span> {t('login.signingIn')}</> : t('login.signIn')}
                        </span>
                      </button>
                    </form>
                    <div className="switcher">
                      <a href="#register" onClick={e => { e.preventDefault(); goTo('register'); }}>
                        {t('login.noAccount')} {t('login.signUp')}
                      </a>
                      <span style={{ margin: '0 8px', color: 'var(--color-text-faint)' }}>·</span>
                      <a href="#forgot" onClick={e => { e.preventDefault(); goTo('forgot'); }}>
                        {t('login.forgotPassword')}
                      </a>
                    </div>
                    <div className="panel-note">
                      {t('login.panelNote')}
                    </div>
                  </section>
                )}

                {/* ──── REGISTER ──── */}
                {step === 'register' && (
                  <section className="page active" data-page="register">
                    <div className={`notice error ${error ? 'show' : ''}`}>{error}</div>
                    <form className="form" onSubmit={handleRegister} noValidate>
                      <div className="field">
                        <label htmlFor="regName">{t('login.fullName')}</label>
                        <input
                          className="input"
                          id="regName"
                          type="text"
                          autoComplete="name"
                          placeholder={t('login.namePlaceholder')}
                          value={displayName}
                          onChange={e => setDisplayName(e.target.value)}
                          autoFocus
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="regEmail">{t('login.emailLabel')}</label>
                        <input
                          className="input"
                          id="regEmail"
                          type="email"
                          inputMode="email"
                          autoComplete="email"
                          placeholder={t('login.emailPlaceholder')}
                          value={email}
                          onChange={e => setEmail(e.target.value)}
                          required
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="regPassword">{t('login.passwordLabel')}</label>
                        <input
                          className="input"
                          id="regPassword"
                          type="password"
                          autoComplete="new-password"
                          placeholder={t('login.passwordMin')}
                          value={password}
                          onChange={e => setPassword(e.target.value)}
                          required
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="regConfirm">{t('login.confirmPassword')}</label>
                        <input
                          className="input"
                          id="regConfirm"
                          type="password"
                          autoComplete="new-password"
                          placeholder={t('login.repeatPassword')}
                          value={confirmPassword}
                          onChange={e => setConfirmPassword(e.target.value)}
                          required
                        />
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={loading}>
                        <span className="btn-label">
                          {loading ? <><span className="spinner"></span> {t('login.creating')}</> : t('login.createAccount')}
                        </span>
                      </button>
                    </form>
                    <div className="switcher">
                      <a href="#login" onClick={e => { e.preventDefault(); goTo('login'); }}>
                        {t('login.haveAccount')}
                      </a>
                    </div>
                  </section>
                )}

                {/* ──── FORGOT PASSWORD ──── */}
                {step === 'forgot' && (
                  <section className="page active" data-page="forgot">
                    <div className={`notice error ${error ? 'show' : ''}`}>{error}</div>
                    <div className={`notice success ${success ? 'show' : ''}`}>{success}</div>
                    <form className="form" onSubmit={handleForgotPassword} noValidate>
                      <div className="field">
                        <label htmlFor="forgotEmail">{t('login.emailLabel')}</label>
                        <input
                          className="input"
                          id="forgotEmail"
                          type="email"
                          inputMode="email"
                          autoComplete="email"
                          placeholder={t('login.emailPlaceholder')}
                          value={email}
                          onChange={e => setEmail(e.target.value)}
                          required
                          autoFocus
                        />
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={loading}>
                        <span className="btn-label">
                          {loading ? <><span className="spinner"></span> {t('login.sending')}</> : t('login.sendReset')}
                        </span>
                      </button>
                    </form>
                    <div className="switcher">
                      <a href="#login" onClick={e => { e.preventDefault(); goTo('login'); }}>
                        {t('login.backToLogin')}
                      </a>
                    </div>
                  </section>
                )}

                {/* ──── RESET PASSWORD ──── */}
                {step === 'reset' && (
                  <section className="page active" data-page="reset">
                    <div className={`notice error ${error ? 'show' : ''}`}>{error}</div>
                    <div className={`notice success ${success ? 'show' : ''}`}>{success}</div>
                    <form className="form" onSubmit={handleResetPassword} noValidate>
                      <div className="field">
                        <label htmlFor="resetPassword">{t('login.newPassword')}</label>
                        <input
                          className="input"
                          id="resetPassword"
                          type="password"
                          autoComplete="new-password"
                          placeholder={t('login.passwordMin')}
                          value={password}
                          onChange={e => setPassword(e.target.value)}
                          required
                          autoFocus
                        />
                      </div>
                      <div className="field">
                        <label htmlFor="resetConfirm">{t('login.confirmNewPassword')}</label>
                        <input
                          className="input"
                          id="resetConfirm"
                          type="password"
                          autoComplete="new-password"
                          placeholder={t('login.repeatNewPassword')}
                          value={confirmPassword}
                          onChange={e => setConfirmPassword(e.target.value)}
                          required
                        />
                      </div>
                      <button className="btn btn-primary" type="submit" disabled={loading}>
                        <span className="btn-label">
                          {loading ? <><span className="spinner"></span> {t('login.resetting')}</> : t('login.resetPassword')}
                        </span>
                      </button>
                    </form>
                    <div className="switcher">
                      <a href="#login" onClick={e => { e.preventDefault(); goTo('login'); }}>
                        {t('login.backToLogin')}
                      </a>
                    </div>
                  </section>
                )}

                {/* ──── MFA ──── */}
                {step === 'mfa' && (
                  <section className="page active" data-page="mfa">
                    <div className="steps">
                      <div className="step active"><span></span></div>
                      <div className="step"><span></span></div>
                    </div>
                    <div className={`notice error ${error ? 'show' : ''}`}>{error}</div>
                    <div className={`notice success ${success ? 'show' : ''}`}>{success}</div>
                    <form id="mfaForm" onSubmit={e => { e.preventDefault(); handleVerifyMfa(); }}>
                      <div className="form">
                        <div className="field">
                          <label htmlFor="mfaCode">{t('login.verificationCode')}</label>
                          <div className="input-wrap">
                            <div className="otp-row">
                              {otp.map((digit, i) => (
                                <input
                                  key={i}
                                  ref={el => { otpRefs.current[i] = el; }}
                                  className="input otp-input"
                                  type="text"
                                  inputMode="numeric"
                                  maxLength={1}
                                  value={digit}
                                  onChange={e => handleOtpChange(i, e.target.value)}
                                  onKeyDown={e => handleOtpKeyDown(i, e)}
                                  autoFocus={i === 0}
                                  required
                                />
                              ))}
                            </div>
                          </div>
                          <span className="error">{t('login.enterCode')}</span>
                        </div>
                        <div className="notice" id="mfaNotice"></div>
                        <div className="field">
                          <label className="check" style={{ fontSize: 'var(--text-sm)' } as React.CSSProperties}>
                            <input type="checkbox" id="trustDevice" />
                            {t('login.trustDevice30')}
                          </label>
                        </div>
                        <button
                          className="btn btn-primary"
                          type="submit"
                          id="mfaSubmit"
                          disabled={loading || otp.join('').length !== 6}
                        >
                          <span className="btn-label">
                            {loading ? <><span className="spinner"></span> {t('login.verifying')}</> : t('login.mfaVerify')}
                          </span>
                        </button>
                        <button
                          className="btn btn-secondary"
                          type="button"
                          id="mfaResend"
                          onClick={handleResend}
                          disabled={loading}
                        >
                          <span className="btn-label">{t('login.resendCode')}</span>
                        </button>
                        <div className="switcher" style={{ textAlign: 'center', marginTop: '12px' } as React.CSSProperties}>
                          <a
                            href="#login"
                            onClick={e => { e.preventDefault(); setStep('login'); setError(''); setOtp(['', '', '', '', '', '']); }}
                          >
                            {t('login.backToLogin')}
                          </a>
                        </div>
                      </div>
                    </form>
                  </section>
                )}

                <p className="legal">
                  {t('login.legalNote')}
                </p>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
