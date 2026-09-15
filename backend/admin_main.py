"""Admin Console 獨立 backend entrypoint（2026-09-10 — 用戶 grill Q2A）

整套 Admin 將來會搬獨立 server — 呢個 file 就係獨立 service 嘅唯一 entrypoint：
    uvicorn admin_main:app --host 127.0.0.1 --port 8002

- 同主站 FastAPI instance 完全分離（自己 process / port / service）
- 共享 app/config + db models（唯讀 import，唔係 runtime 依賴）
- 淨 include：auth（登入攞 JWT）+ admin（/api/v1/admin/* — require_superadmin + BYPASSRLS）
- 搬 server = 成個 backend folder 搬走 + 行呢個 entrypoint，零 code 改動
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.tenant import TenantMiddleware
from app.middleware.ai_session import AISessionMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="PenguinCRM Admin Console API", version="1.0.0", lifespan=lifespan)

# CORS — 主站 origins + adm.penguincrm.io（admin 前端獨立 domain）
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
for extra in ("https://adm.penguincrm.io", "https://adm.kinet-poc.com",
              "http://localhost:5174", "https://adm-api.kinet-poc.com",
              "https://adm-api.penguincrm.io"):
    if extra not in origins:
        origins.append(extra)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AISessionMiddleware)
app.add_middleware(TenantMiddleware)

# Admin console routers
from app.routers import auth  # noqa: E402 — login/refresh（主站同一 JWT 信任域）
from app.routers import admin  # noqa: E402 — /api/v1/admin/*（BYPASSRLS + require_superadmin）
from app.routers import i18n  # noqa: E402 — i18n translation mgmt（admin editor）

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(i18n.router)

# Error monitoring（2026-09-12）— admin API 係獨立 app，一定要自己掛，
# 唔係 admin 側嘅 500 就完全冇記錄（踩過：audit endpoint 500 但 error_events 空）
from app.services.error_monitor import ErrorMonitorMiddleware  # noqa: E402

app.add_middleware(ErrorMonitorMiddleware)
