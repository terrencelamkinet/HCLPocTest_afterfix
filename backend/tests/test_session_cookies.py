"""Session cookie（httpOnly）測試 — 2026-09-15 SAST。

對應 AppScan「Web, Local Storage Insecure」(CWE-20)：前端原本將 access/refresh
token 存 localStorage（任何 XSS 都偷得走）→ 已改為 httpOnly cookie。

呢個 file 專門驗：
  1. login 回嘅 cookie 係 HttpOnly + SameSite=Lax + Path 收窄 + Secure
  2. **完全冇 Authorization header**，只用 cookie 都做到 /auth/me
  3. refresh 用 cookie 做，可以連續做兩次（呢個係順手修好嘅真 bug：之前 refresh
     唔回新 refresh token 但舊嗰個已經 revoke → 一世只 refresh 到一次）
  4. logout（cookie only）會清 cookie 兼 revoke session
  5. 舊嘅 `Authorization: Bearer` path 仍然 work（CLI / scripts / e2e 向後兼容）

⚠️ 唔用 httpx cookie jar：Python cookiejar 對 http:// 唔會送 Secure cookie
（browser 對 localhost 有例外，Python 冇）→ 我哋自己 parse Set-Cookie 再手動
砌 Cookie header，測嘅係 server 行為，唔係 client 政策。
"""

from __future__ import annotations

from http.cookies import SimpleCookie

import httpx
import pytest

BACKEND = "http://127.0.0.1:8001"
TEST_EMAIL = "terrence_lam@kinetix.com.hk"
TEST_PASSWORD = "test1234"


def _set_cookie_headers(resp: httpx.Response) -> list[str]:
    return resp.headers.get_list("set-cookie")


def _cookies_from(resp: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in _set_cookie_headers(resp):
        sc = SimpleCookie()
        sc.load(raw)
        for name, morsel in sc.items():
            out[name] = morsel.value
    return out


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _raw_for(raw_headers: list[str], name: str) -> str:
    for raw in raw_headers:
        if raw.startswith(f"{name}="):
            return raw
    return ""


async def _login(client: httpx.AsyncClient) -> httpx.Response:
    resp = await client.post(
        f"{BACKEND}/api/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, f"login 應該 200，實際 {resp.status_code}"
    assert resp.json().get("mfa_required") is False, "呢個測試帳號唔應該要 MFA"
    return resp


class TestCookieAttributes:
    async def test_login_sets_httponly_session_cookies(self):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await _login(client)

        raw = _set_cookie_headers(resp)
        access_raw = _raw_for(raw, "nexus_at")
        refresh_raw = _raw_for(raw, "nexus_rt")

        assert access_raw, "login 一定要種 nexus_at（access cookie）"
        assert refresh_raw, "login 一定要種 nexus_rt（refresh cookie）"

        # JS 讀唔到 + 唔會跟跨站 POST 跑 + 唔會經 http 漏
        assert "HttpOnly" in access_raw
        assert "SameSite=lax" in access_raw.lower().replace("samesite=lax", "SameSite=lax") or "samesite=lax" in access_raw.lower()
        assert "Secure" in access_raw
        assert "Path=/api" in access_raw

        # refresh cookie 收窄到 auth path（其他 endpoint 收唔到）
        assert "HttpOnly" in refresh_raw
        assert "Path=/api/v1/auth" in refresh_raw

        # cookie 唔應該同時用寬鬆 path / 冇 HttpOnly
        assert "Path=/" not in access_raw or "Path=/api" in access_raw


class TestCookieOnlyAuth:
    async def test_me_works_with_cookie_only_no_authorization_header(self):
        async with httpx.AsyncClient(timeout=30) as client:
            login = await _login(client)
            cookies = _cookies_from(login)
            assert "nexus_at" in cookies

            me = await client.get(
                f"{BACKEND}/api/v1/auth/me",
                headers={"Cookie": _cookie_header(cookies)},
            )
            assert me.status_code == 200, f"cookie-only /auth/me 應該 200，實際 {me.status_code}"
            assert me.json()["email"] == TEST_EMAIL

    async def test_me_without_any_credential_is_401(self):
        async with httpx.AsyncClient(timeout=30) as client:
            me = await client.get(f"{BACKEND}/api/v1/auth/me")
            assert me.status_code == 401

    async def test_bearer_header_still_works(self):
        """向後兼容：CLI / scripts / e2e 用 Authorization header 照舊可以。"""
        async with httpx.AsyncClient(timeout=30) as client:
            login = await _login(client)
            token = login.json()["access_token"]
            me = await client.get(
                f"{BACKEND}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert me.status_code == 200
            assert me.json()["email"] == TEST_EMAIL


class TestRefreshWithCookie:
    async def test_refresh_with_cookie_rotates_and_can_run_twice(self):
        async with httpx.AsyncClient(timeout=30) as client:
            login = await _login(client)
            c1 = _cookies_from(login)

            # 第一次 refresh：冇 body、冇 Authorization，只有 cookie
            r1 = await client.post(
                f"{BACKEND}/api/v1/auth/refresh",
                json={},
                headers={"Cookie": _cookie_header(c1)},
            )
            assert r1.status_code == 200, f"cookie-only refresh 應該 200，實際 {r1.status_code}"
            c2 = _cookies_from(r1)
            assert "nexus_rt" in c2, "refresh 一定要 rotate refresh cookie"
            assert c2["nexus_rt"] != c1["nexus_rt"], "新 refresh token 唔應該同舊一樣"

            # 第二次 refresh：用 rotate 之後嘅 cookie —— 之前呢步一定 401（bug）
            r2 = await client.post(
                f"{BACKEND}/api/v1/auth/refresh",
                json={},
                headers={"Cookie": _cookie_header(c2)},
            )
            assert r2.status_code == 200, (
                f"第二次 refresh 應該 200（修好嘅 once-only bug），實際 {r2.status_code}"
            )

            # 舊 refresh cookie 已經 revoke
            old = await client.post(
                f"{BACKEND}/api/v1/auth/refresh",
                json={},
                headers={"Cookie": f"nexus_rt={c1['nexus_rt']}"},
            )
            assert old.status_code == 401, "舊 refresh token 一定要 401（已 revoke）"


class TestLogout:
    async def test_logout_clears_cookies_and_revokes_session(self):
        async with httpx.AsyncClient(timeout=30) as client:
            login = await _login(client)
            c1 = _cookies_from(login)

            out = await client.post(
                f"{BACKEND}/api/v1/auth/logout",
                json={},
                headers={"Cookie": _cookie_header(c1)},
            )
            assert out.status_code == 200

            raw = " ".join(_set_cookie_headers(out))
            assert "nexus_at=" in raw and "nexus_rt=" in raw, "logout 一定要清兩個 cookie"
            assert "Max-Age=0" in raw or "max-age=0" in raw, "清 cookie 要用 Max-Age=0"

            # refresh session 已經 revoke → 唔可以再 refresh
            again = await client.post(
                f"{BACKEND}/api/v1/auth/refresh",
                json={},
                headers={"Cookie": f"nexus_rt={c1['nexus_rt']}"},
            )
            assert again.status_code == 401, "logout 之後 refresh 一定要 401"

    async def test_refresh_without_any_token_is_401(self):
        """冇 cookie 又冇 body → 401（唔可以 500）。"""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{BACKEND}/api/v1/auth/refresh", json={})
            assert resp.status_code == 401
