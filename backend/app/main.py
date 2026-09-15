from contextlib import asynccontextmanager
import asyncio
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import engine, Base
from app.models import User, Session, Tenant, TenantMember  # Register all models
from app.models.crm import Company, Contact, Touchpoint, Task, NameCard, Note, ActivityLog, Tag  # Register CRM models
from app.models.crm_module_b import DealPipeline, DealStage, Deal, Product, DealLineItem, Quote, QuoteItem, SalesReport, ModuleSetting  # Register Module B models
from app.models.crm_module_c import AiDraft, Expense, PersonalNote  # Register Batch B/C module models
from app.models.notification import Notification, NotificationPreference  # Register Notification models
from app.models.dashboard_layout import DashboardLayout  # Register Dashboard layout model
from app.models.integration import Integration, OAuthState  # Register Integration models
from app.models.whatsapp import WhatsAppMapping, WhatsAppOTP  # Register WhatsApp models
from app.models.telegram_bot import TelegramBotMapping  # Register Telegram models
from app.models.im_push import IMDeliveryPref, PushLog  # Register IM Push models
from app.models.bible_reading import BibleReadingProgress, BibleVerse  # Register Bible reading models
from app.models.oauth_client import OAuthClientSetting  # Register OAuth client settings model
from app.models.ai import Agent, AISession, Message, Tool, ActionRequest, Quota, UsageEvent, ModelProfile, ProviderCredential, ProviderHealth, SecretarySettings, ChannelCredential, PendingAIQuestion  # Register AI models
from app.middleware.tenant import TenantMiddleware
from app.middleware.ai_session import AISessionMiddleware

# 2026-09-10: app 嘅 INFO log 一直靜默無聲。因為冇任何地方設定 logging，
# root logger 停留喺 WARNING，所以 app code 所有 logger.info(...)（閘嘅決定、
# agent loop 遙測、vision 失敗、Redis fail-open）**從來冇入過 journal** ——
# 令「將來吞訊息一眼睇得出」呢個講法唔成立。
# 喺 import 時設定一次，唔會干擾 uvicorn 自己嘅 logger。
import logging as _logging

_root_logger = _logging.getLogger()
if _root_logger.level > _logging.INFO or _root_logger.level == _logging.NOTSET:
    _root_logger.setLevel(_logging.INFO)
if not _root_logger.handlers:
    _h = _logging.StreamHandler()
    _h.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _root_logger.addHandler(_h)

# 2026-09-11: 上面將 root 設做 INFO，連 sqlalchemy.engine 都跟住 INFO →
# 每一個 SQL statement 都 log 一行（journal 2 分鐘 ~10k 行，grep time out）。
# 將 SQLAlchemy 嘅 loggers 壓到 WARNING（app 自己嘅 INFO 照樣出）。
for _sqlalchemy_logger in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.orm"):
    _logging.getLogger(_sqlalchemy_logger).setLevel(_logging.WARNING)


def _acquire_singleton_lock(path: str) -> bool:
    """PID-aware singleton lock（多 process 只有一個 worker 行）。

    2026-09-10 實錘：舊 code 用 O_EXCL 建 lock 但唔寫 PID、又冇 cleanup，
    一 restart 就留低 stale lock → worker 永久停 ── namecard OCR worker 因此
    停擺，用戶掃到嘅名片全部卡 pending_ocr，唔會建立/更新 contacts。
    而家：lock 寫入 PID；已有 lock 時檢查 PID 生死，死咗就接管。
    """
    def _create() -> int:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        return fd

    try:
        os.close(_create())
        return True
    except FileExistsError:
        pass
    try:
        with open(path) as f:
            pid = int((f.read() or "0").strip() or 0)
    except FileNotFoundError:
        pid = 0
    except (ValueError, OSError):
        pid = 0
    alive = False
    if pid > 0:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True  # 有 process（可能唔同 user）揸住
    if alive:
        return False
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    try:
        os.close(_create())
        return True
    except OSError:
        return False


def _release_singleton_lock(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure nexus_auth and nexus_crm schemas exist.
    # IMPORTANT: with gunicorn --preload + N workers, lifespan runs once per
    # worker. create_all uses checkfirst (no-op when tables exist), but 4
    # workers racing the initial DDL can deadlock on table locks. Use a
    # file-based lock so only the first worker does DDL; others skip.
    ddl_lock = "/tmp/nexus_crm_ddl.lock"
    acquired = False
    try:
        os.makedirs("/tmp", exist_ok=True)
        fd = os.open(ddl_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        acquired = True
    except FileExistsError:
        acquired = False
    if acquired:
        try:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS nexus_auth"))
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS nexus_crm"))
                await conn.run_sync(Base.metadata.create_all)
        finally:
            try:
                os.remove(ddl_lock)
            except OSError:
                pass

    # Telegram inbound: webhook mode (production) OR getUpdates poller (fallback)
    if not settings.tg_use_webhook:
        from app.services.telegram_inbound import poll_once

        poller_stop = asyncio.Event()

        async def _tg_poll_loop():
            from app.db import async_session
            import logging as _logging
            while not poller_stop.is_set():
                try:
                    async with async_session() as db:
                        await poll_once(db)
                except Exception as e:  # noqa: BLE001 — poller must never crash the app, but must NOT be silent
                    _logging.getLogger("telegram_inbound").exception(
                        "poll_once crashed: %s", e
                    )
                try:
                    await asyncio.wait_for(poller_stop.wait(), timeout=1)
                except asyncio.TimeoutError:
                    continue

        poller_task = asyncio.create_task(_tg_poll_loop())
    else:
        # Webhook mode: spawn Redis queue consumers (one per worker).
        # BRPOP guarantees each update goes to exactly one worker.
        from app.services.telegram_inbound import webhook_queue_consumer
        queue_stop = asyncio.Event()
        queue_task = asyncio.create_task(webhook_queue_consumer(queue_stop))

    # Daily Briefing scheduler — every 15 min, single worker (file lock so the
    # N gunicorn workers don't all run it). Honors IMDeliveryPref channel gate
    # + weekend_mute + quiet_hours; per-user greeting_slots decide timing.
    if not settings.briefing_scheduler_enabled:
        briefing_task = None
        brief_owner = False
        briefing_stop = None
        _sched_lock = None
    else:
        _sched_lock = "/tmp/nexus_crm_briefing.lock"
        brief_owner = False
        brief_owner = _acquire_singleton_lock(_sched_lock)

        briefing_stop = asyncio.Event()

        async def _briefing_loop():
            from app.services.briefing_scheduler import run_scheduler
            import logging as _blog
            while not briefing_stop.is_set():
                try:
                    stats = await run_scheduler()
                    _blog.getLogger("briefing_scheduler").info(
                        "run: %s due, %s sent, %s skipped, %s failed (%s scanned)",
                        stats.get("due"), stats.get("sent"), stats.get("skipped"),
                        stats.get("failed"), stats.get("scanned"),
                    )
                except Exception as e:  # noqa: BLE001 — must never crash the app
                    _blog.getLogger("briefing_scheduler").exception(
                        "run_scheduler crashed: %s", e
                    )
                try:
                    await asyncio.wait_for(briefing_stop.wait(), timeout=15 * 60)
                except asyncio.TimeoutError:
                    continue

        if brief_owner:
            briefing_task = asyncio.create_task(_briefing_loop())
        else:
            briefing_task = None

    # Notification scan loop — every 5 min, single worker (file lock so the
    # N gunicorn workers don't all run it). Pushes due-today / deadline /
    # calendar-reminder notifications per user. Group-key dedup prevents repeats.
    notif_scan_lock = "/tmp/nexus_crm_notif_scan.lock"
    notif_scan_owner = False
    notif_scan_stop = None
    notif_scan_task = None
    notif_scan_owner = _acquire_singleton_lock(notif_scan_lock)

    if notif_scan_owner:
        from app.services.notification_scan import run_scan_loop
        notif_scan_stop = asyncio.Event()
        notif_scan_task = asyncio.create_task(run_scan_loop(notif_scan_stop))

    # NameCard OCR worker — every 8s, single worker (file lock). Processes pending_ocr
    # namecard rows → OCR pipeline → 中央通知. Persistent loop: 唔受 gunicorn request
    # timeout 影響（BackgroundTasks 會俾 gunicorn timeout kill — 卡永遠 pending）。
    nc_ocr_lock = "/tmp/nexus_crm_namecard_ocr.lock"
    nc_ocr_owner = False
    nc_ocr_stop = None
    nc_ocr_task = None
    nc_ocr_owner = _acquire_singleton_lock(nc_ocr_lock)

    if nc_ocr_owner:
        from app.routers.crm import namecard_process_pending
        import logging as _nclog
        nc_ocr_stop = asyncio.Event()

        async def _nc_ocr_loop():
            while not nc_ocr_stop.is_set():
                try:
                    _done = await namecard_process_pending()
                    if _done:
                        _nclog.getLogger("namecard_ocr").info("processed %s pending card(s)", _done)
                except Exception as e:  # noqa: BLE001 — must never crash the app
                    _nclog.getLogger("namecard_ocr").exception("namecard tick crashed: %s", e)
                try:
                    await asyncio.wait_for(nc_ocr_stop.wait(), timeout=8)
                except asyncio.TimeoutError:
                    continue

        nc_ocr_task = asyncio.create_task(_nc_ocr_loop())

    # Action expiry sweep — REMOVED 2026-09-10 (operator: 「Remove all 草稿」).
    # There are no persisted pending action_requests any more: a prepared write
    # lives only in a short-lived cache (app.services.pending_writes) that
    # expires on its own, and becomes an ActionRequest row already-final
    # ('executed') at the moment of the confirmed write. Nothing accumulates,
    # so there is nothing left to sweep. app/services/action_expiry.py is now
    # unused (kept on disk for the historical record only).

    yield
    # Cleanup: stop briefing loop + release scheduler lock (stale lock would
    # permanently disable the loop on next restart — O_EXCL would fail forever)
    if brief_owner and briefing_stop is not None and briefing_task is not None:
        briefing_stop.set()
        try:
            await asyncio.wait_for(briefing_task, timeout=5)
        except Exception:
            pass
        if _sched_lock:
            try:
                os.remove(_sched_lock)
            except FileNotFoundError:
                pass
    if not settings.tg_use_webhook:
        poller_stop.set()
        try:
            await asyncio.wait_for(poller_task, timeout=5)
        except Exception:
            pass
    else:
        queue_stop.set()
        try:
            await asyncio.wait_for(queue_task, timeout=5)
        except Exception:
            pass
    # (action expiry sweep removed 2026-09-10 — no pending drafts persist)

    # Stop notification scan loop + release lock
    if notif_scan_owner and notif_scan_stop is not None and notif_scan_task is not None:
        notif_scan_stop.set()
        try:
            await asyncio.wait_for(notif_scan_task, timeout=5)
        except Exception:
            pass
        try:
            os.remove(notif_scan_lock)
        except OSError:
            pass
    # Stop namecard OCR worker + release lock
    if nc_ocr_owner and nc_ocr_stop is not None and nc_ocr_task is not None:
        nc_ocr_stop.set()
        try:
            await asyncio.wait_for(nc_ocr_task, timeout=5)
        except Exception:
            pass
        try:
            os.remove(nc_ocr_lock)
        except OSError:
            pass
    if briefing_task:
        try:
            briefing_stop.set()
            await asyncio.wait_for(briefing_task, timeout=5)
        except Exception:
            pass
        try:
            os.remove(_sched_lock)
        except OSError:
            pass
    await engine.dispose()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

# CORS
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AISessionMiddleware)
app.add_middleware(TenantMiddleware)

# Error monitoring（Critical，2026-09-12）— 最外層，捕捉未處理 exception + 5xx
from app.services.error_monitor import ErrorMonitorMiddleware  # noqa: E402

app.add_middleware(ErrorMonitorMiddleware)

# Mount routers
from app.routers import auth
from app.routers import crm
from app.routers import crm_module_b
from app.routers import crm_module_settings
from app.routers import crm_module_c
from app.routers import crm_notifications
from app.routers import crm_todo
from app.routers import crm_renewals
from app.routers import dashboard_layout
from app.routers import crm_integrations
from app.routers import admin_oauth
from app.routers import whatsapp
from app.routers import telegram
app.include_router(auth.router)
app.include_router(crm.router)
app.include_router(crm_module_b.router)
app.include_router(crm_module_settings.router)
app.include_router(crm_notifications.router)
app.include_router(crm_todo.router)
app.include_router(crm_renewals.router)
app.include_router(dashboard_layout.router)
app.include_router(crm_module_c.router)
app.include_router(crm_integrations.router)
app.include_router(admin_oauth.router)
app.include_router(whatsapp.router)
app.include_router(telegram.router)
from app.routers import im_push
app.include_router(im_push.router)
from app.routers import ai
from app.routers import ai_rag
app.include_router(ai.router)
app.include_router(ai_rag.router)
from app.routers import ai_secretary
app.include_router(ai_secretary.router)
from app.routers import ai_core
from app.routers import geo
app.include_router(ai_core.router)
app.include_router(geo.router)

# Admin console（2026-09-09 — nexus_admin BYPASSRLS；tenant env 冇 DB URL 就自動停用）
try:
    from app.routers import admin, i18n
    app.include_router(admin.router)
    app.include_router(i18n.router)  # i18n resources = 任何 tenant 讀；entries write = require_superadmin
except Exception as _admin_err:  # pragma: no cover
    import logging
    logging.getLogger("app").warning("admin router disabled: %s", _admin_err)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "nexus-auth"}
