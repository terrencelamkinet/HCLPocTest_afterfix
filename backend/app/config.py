from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ⚠️ 只用喺 main.py 嘅 FastAPI(title=...) = OpenAPI 標題（純顯示）。
    # 確認過同 JWT issuer / audience 無關，改名唔會令任何 session 失效。
    app_name: str = "Penguin CRM API"
    # 2026-09-15 SAST：debug 預設 False（之前 default True，prod .env 冇 NEXUS_DEBUG
    # 就會令 debug 路徑喺 production 生效）；dev-login endpoint 已於 v7.88.11 整個刪走。
    debug: bool = False
    # Public-facing base URL (for OAuth redirect URIs behind cloudflared).
    # Set in production .env: PUBLIC_BASE_URL=https://www.penguincrm.io
    public_base_url: str = ""

    # Database — via PgBouncer (transaction pool, port 6432) for 50k-scale
    # connection multiplexing. Direct 5432 fallback kept in comments.
    #   direct: postgresql+asyncpg://gg_fighter:CHANGE_ME@127.0.0.1:5432/nexus_crm
    database_url: str = ""  # NEXUS_DATABASE_URL（必填）— 2026-09-15 SAST：移除 hardcoded
    # credential default（gg_fighter 密碼之前 hardcode 喺 repo，已 rotate + 移入 .env）

    # JWT — RS256 asymmetric for tenant security
    jwt_private_key_path: str = "keys/private.pem"
    jwt_public_key_path: str = "keys/public.pem"
    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 1440  # 24h (was 15min)
    refresh_token_expire_days: int = 1

    # PgBouncer (transaction pool) — same URL as database_url; kept for
    # components that need the dedicated nexus_app role (e.g. migrations).
    app_database_url: str = ""  # NEXUS_APP_DATABASE_URL（migrations 用；2026-09-15 同理移入 .env）

    # Briefing scheduler — BYPASSRLS role so it can scan ALL users' settings.
    briefing_database_url: str = ""  # NEXUS_BRIEFING_DATABASE_URL
    briefing_scheduler_enabled: bool = True  # NEXUS_BRIEFING_SCHEDULER_ENABLED (default ON — Daily Briefing live)

    # Admin console — nexus_admin BYPASSRLS role (direct 5432 — not in pgbouncer userlist).
    # NEXUS_ADMIN_DATABASE_URL / NEXUS_ADMIN_EMAILS（comma-separated）（2026-09-09 Admin 後台）
    nexus_admin_database_url: str = ""
    nexus_admin_emails: str = ""

    # Gemini Enterprise / Vertex AI（香港 external search — 2026-09-08）
    # NEXUS_VERTEX_PROJECT / NEXUS_VERTEX_LOCATION / NEXUS_GOOGLE_APPLICATION_CREDENTIALS
    vertex_project: str = ""  # e.g. frameshift-labs
    vertex_location: str = "us-central1"
    google_application_credentials: str = ""
    # 2026-09-11: Sign in with Google (GIS ID-token flow). This is the PUBLIC OAuth
    # client ID — it may ship to the browser. The matching client SECRET is not
    # needed: the ID-token flow verifies Google's signed token rather than
    # exchanging a code, so there is nothing secret to hold server-side.
    google_client_id: str = ""

    # Redis (for OTP cache)
    redis_url: str = "redis://127.0.0.1:6379/0"

    # Redis cache for hot, rarely-changing AI lookups (provider keys / model
    # profiles). Every knob is optional with a safe default — unset = sane.
    # .env needs the NEXUS_ prefix (pitfall #3): NEXUS_CACHE_ENABLED,
    # NEXUS_CACHE_TTL_SECONDS, NEXUS_CACHE_TIMEOUT_MS,
    # NEXUS_CACHE_COOLDOWN_SECONDS, NEXUS_CACHE_MAX_CONNECTIONS.
    cache_enabled: bool = True
    cache_ttl_seconds: int = 60           # default entry TTL (~60s)
    cache_timeout_ms: int = 200           # connect + socket timeout (hard cap 200)
    cache_cooldown_seconds: float = 30.0  # breaker window after a failure
    cache_max_connections: int = 20       # pool size


    # Email (SMTP for OTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    mfa_from_email: str = "noreply@nexus-crm.com"

    # ── Session cookie（2026-09-15 SAST：token 由 localStorage 搬入 httpOnly）──
    # 見 app/services/session_cookies.py。默認 True = fail-safe（生產 HTTPS）。
    # 只有本地 HTTP 驗證（pytest / curl）需要 NEXUS_COOKIE_SECURE=false，
    # 因為 Python cookiejar 唔似 browser 會對 localhost 放行 Secure cookie。
    cookie_secure: bool = True
    # 留空 = host-only cookie（最安全）。跨 subdomain 共享才需要設。
    cookie_domain: str = ""

    # CORS
    allowed_origins: str = "http://localhost:5173,https://nexus-crm.kinet-poc.com,https://www.penguincrm.io,https://penguincrm.io"

    # AI Provider keys
    deepseek_api_key: str = ""
    gemini_api_key: str = ""

    # Geo — address autocomplete / reverse geocoding（server-side proxy）
    geo_provider: str = "auto"   # auto（有 key 用 geoapify，冇用 photon）| photon | geoapify
    geoapify_api_key: str = ""   # GEOAPIFY_API_KEY — free 3000 req/day

    # WhatsApp Cloud API
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_webhook_verify_token: str = ""
    tg_webhook_secret: str = ""       # NEXUS_TG_WEBHOOK_SECRET — validates X-Telegram-Bot-Api-Secret-Token
    tg_use_webhook: bool = False      # NEXUS_TG_USE_WEBHOOK — true = webhook mode (poller disabled)
    whatsapp_app_secret: str = ""
    whatsapp_template_name: str = ""  # NEXUS_WHATSAPP_TEMPLATE_NAME — approved Meta template for 24h-window fallback

    # Integration / OAuth
    api_base_url: str = "http://localhost:8001"
    integration_client_ids: dict = {
        "google_calendar": "",
        "outlook_calendar": "",
        "gmail": "",
        "outlook_mail": "",
        "slack": "",
        "zoom": "",
        "whatsapp": "",
        "teams": "",
        "google_drive": "",
        "dropbox": "",
        "onedrive": "",
        "linkedin": "",
        "facebook": "",
        "notion": "",
        "stripe": "",
        "quickbooks": "",
        "mailchimp": "",
        "hubspot": "",
    }

    cron_api_key: str = ""  # Cron-Api-Key for scheduled jobs (NEXUS_CRON_API_KEY)

    model_config = {"env_prefix": "NEXUS_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

settings = Settings()
