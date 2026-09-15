"""HttpOnly session cookie 支援。

2026-09-15 SAST（AppScan HCLPocTest：「Web, Local Storage Insecure」CWE-20 ×11）
-----------------------------------------------------------------------------
原本前端將 access/refresh token 存喺 `localStorage['nexus_crm_auth']` —— 任何
XSS（即使將來新加嘅）都可以一次過偷走 24 小時有效嘅 token。改為 httpOnly cookie
之後 **JS 完全讀唔到 token**，連 XSS 都偷唔到；同時前端照樣運作。

設計
----
- `nexus_at` — access token。Path=/api、HttpOnly、SameSite=Lax、Secure。
- `nexus_rt` — refresh token。Path=/api/v1/auth（收窄：只有 refresh/logout 收到）、
  HttpOnly、SameSite=Lax、Secure。
- 同源：前端 fetch 用 `credentials: 'include'`；生產靠 nginx proxy、dev 靠 Vite
  proxy，API 同 SPA 同一個 origin → SameSite=Lax 已經足夠擋 CSRF（Lax 唔會跟
  跨站 POST/PUT/DELETE 送 cookie，而所有寫入 endpoint 都唔係 GET）。
- **後端繼續支援 `Authorization: Bearer`**（CLI／scripts／e2e／舊 client 唔使改）；
  邊緣（`middleware/tenant.py`）會將 cookie 還原成 Bearer header，所以 router
  層面完全唔需要知 cookie 存在。
- `NEXUS_COOKIE_SECURE=false` 只係俾本地 HTTP 驗證用（Python cookiejar 唔似
  browser 會對 localhost 例外開放 Secure）；生產必須保持 True。
"""

from __future__ import annotations

from fastapi import Request, Response

from app.config import settings

COOKIE_ACCESS = "nexus_at"
COOKIE_REFRESH = "nexus_rt"
ACCESS_PATH = "/api"
REFRESH_PATH = "/api/v1/auth"

# access cookie 比 token 本身早 60 秒到期（避免邊界上「cookie 仲喺但 token 過期」）
_ACCESS_MAX_AGE = max(60, settings.access_token_expire_minutes * 60 - 60)
# refresh cookie 留 2 小時緩衝（同原本前端 localStorage 嘅 22h 一致）
_REFRESH_MAX_AGE = max(300, settings.refresh_token_expire_days * 86400 - 2 * 3600)


def _cookie_kwargs(path: str, max_age: int) -> dict:
    kw: dict = {
        "path": path,
        "max_age": max_age,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
    }
    if settings.cookie_domain:
        # 留空 = host-only cookie（最安全，跨 subdomain 唔會漏）
        kw["domain"] = settings.cookie_domain
    return kw


def set_session_cookies(response: Response, access_token: str = "", refresh_token: str = "") -> None:
    """種 session cookie。access_token 空（例如 MFA 未完成）就唔種 access cookie。"""
    if access_token:
        response.set_cookie(COOKIE_ACCESS, access_token, **_cookie_kwargs(ACCESS_PATH, _ACCESS_MAX_AGE))
    if refresh_token:
        response.set_cookie(COOKIE_REFRESH, refresh_token, **_cookie_kwargs(REFRESH_PATH, _REFRESH_MAX_AGE))


def clear_session_cookies(response: Response) -> None:
    """登出：兩個 cookie 都要清（path 唔同，要分開刪）。"""
    for name, path in ((COOKIE_ACCESS, ACCESS_PATH), (COOKIE_REFRESH, REFRESH_PATH)):
        response.delete_cookie(
            name,
            path=path,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            domain=settings.cookie_domain or None,
        )


def access_token_from_request(request: Request) -> str:
    """Authorization: Bearer 優先（向後兼容），否則讀 cookie。"""
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
        if token:
            return token
    return request.cookies.get(COOKIE_ACCESS) or ""


def refresh_token_from_request(request: Request, body_token: str | None = None) -> str:
    """body（舊 client）優先，否則讀 cookie（新前端唔再傳 body）。"""
    return (body_token or "").strip() or (request.cookies.get(COOKIE_REFRESH) or "")
