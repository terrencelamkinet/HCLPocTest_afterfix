"""
Integration API Tests — tenant-isolated, async.

Run against running backend:
  source venv/bin/activate && pytest tests/test_integrations.py -v --capture=no

Requires: backend running on http://localhost:8001
"""
import pytest
import httpx
import uuid
from jose import jwt
from datetime import datetime, timezone

from app.config import settings
from app.services.auth_service import _load_private_key

BACKEND_URL = "http://localhost:8001"
KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
ALT_TENANT = "00000000-0000-0000-0000-000000000002"
TEST_USER = "9f3e7b11-e529-4cf8-82a6-2a62e4e5b643"
ALT_USER = "aaaaaaaa-e529-4cf8-82a6-2a62e4e5bbbb"

TEST_PROVIDER = "google_calendar"
TEST_PROVIDER_DISPLAY = "Google Calendar"

# Placeholder-path provider（crm_integrations._TOKEN_ENDPOINTS 冇佢）：用嚟測「完整
# OAuth 連線成功」流程。google / microsoft 系有真 token endpoint，fake code 必定被
# provider 拒（502），所以佢哋只可以做 graceful-failure 測試，唔可以做 happy path。
CONNECT_PROVIDER = "notion"
CONNECT_PROVIDER_DISPLAY = "Notion"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(sub: str, tenant_id: str, email: str = "test@test.com", role: str = "admin") -> str:
    """Generate a JWT for testing."""
    payload = {
        "sub": sub,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
    }
    return jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)


@pytest.fixture
def auth_headers(seeded_test_tenants):
    return {"Authorization": f"Bearer {_make_token(TEST_USER, KINETIX_TENANT)}"}


@pytest.fixture
def alt_auth_headers(seeded_test_tenants):
    """Different tenant, different user."""
    return {"Authorization": f"Bearer {_make_token(ALT_USER, ALT_TENANT, 'alt@test.com')}"}


# Providers 分兩類（睇 crm_integrations._TOKEN_ENDPOINTS）：
#   EXCHANGE_PROVIDERS    → 有真 token endpoint；fake code 被 provider 拒 → 502（正確行為）
#   PLACEHOLDER_PROVIDERS → 未有真 endpoint；callback 直接落 placeholder token → 200
# 2026-09-15：原本呢批 test 當所有 provider 都回 placeholder，所以一直紅（502 != 200）。
EXCHANGE_PROVIDERS = [
    "google_calendar",
    "gmail",
    "google_drive",
    "outlook_calendar",
    "outlook_mail",
]
PLACEHOLDER_PROVIDERS = [
    "slack",
    "zoom",
    "whatsapp",
    "teams",
    "dropbox",
    "onedrive",
    "linkedin",
    "facebook",
    "notion",
    "stripe",
    "quickbooks",
    "mailchimp",
    "hubspot",
]


async def _oauth_connect(client: httpx.AsyncClient, headers: dict, provider: str) -> dict:
    """行一次 start → callback，回 integration record（assert 全程 200）。"""
    start = await client.post(
        f"{BACKEND_URL}/api/v1/integrations/oauth/start",
        headers=headers,
        json={"provider": provider},
    )
    assert start.status_code == 200, f"oauth/start {provider} → {start.status_code}"
    state = start.json()["state"]
    cb = await client.post(
        f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
        headers=headers,
        json={"code": f"code_{provider}", "state": state},
    )
    assert cb.status_code == 200, f"oauth/callback {provider} → {cb.status_code} {cb.text[:120]}"
    return cb.json()


@pytest.fixture(autouse=True)
async def cleanup_integrations():
    """每個 test 前後都清走本 tenant 嘅 integration，確保 test 唔留殘留。

    2026-09-15：之前只喺 test 之前清 → 最後一個 test 留低嘅 row 會殘留 DB。
    """
    await _purge_test_integrations()
    yield
    await _purge_test_integrations()


async def _purge_test_integrations() -> None:
    async with httpx.AsyncClient() as client:
        token = _make_token(TEST_USER, KINETIX_TENANT)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(f"{BACKEND_URL}/api/v1/integrations", headers=headers)
        if resp.status_code == 200:
            for item in resp.json():
                await client.delete(
                    f"{BACKEND_URL}/api/v1/integrations/{item['id']}", headers=headers
                )


# ===========================================================================
# Unauthenticated access
# ===========================================================================

class TestUnauthenticated:

    async def test_list_integrations_no_auth(self):
        """Without a Bearer token, the endpoint should return 403 (Tenant not identified)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/api/v1/integrations")
        assert resp.status_code == 403
        assert "Tenant not identified" in resp.json().get("detail", "")

    async def test_oauth_start_no_auth(self):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                json={"provider": TEST_PROVIDER},
            )
        assert resp.status_code == 403

    async def test_oauth_callback_no_auth(self):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                json={"code": "x", "state": "y"},
            )
        assert resp.status_code == 403


# ===========================================================================
# Fresh state — no integrations connected yet
# ===========================================================================

class TestFreshIntegration:

    async def test_list_integrations_empty(self, auth_headers):
        """Fresh user should have an empty list."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_get_nonexistent_integration(self, auth_headers):
        fake_id = str(uuid.uuid4())
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations/{fake_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 404


# ===========================================================================
# OAuth start flow
# ===========================================================================

class TestOAuthStart:

    async def test_start_google_calendar(self, auth_headers):
        """Starting OAuth for Google Calendar should return state + oauth_url."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": "google_calendar"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert len(data["state"]) > 20  # CSRF token
        assert "oauth_url" in data
        assert "google.com" in data["oauth_url"]
        assert data["provider"] == "google_calendar"
        # Verify redirect_uri points to frontend callback
        assert "/marketplace/oauth/callback" in data["oauth_url"]

    async def test_start_missing_provider(self, auth_headers):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={},
            )
        assert resp.status_code == 400
        assert "provider" in resp.json().get("detail", "")

    async def test_start_webhook_provider(self, auth_headers):
        """Webhook-based providers (Zapier, Make) should return empty oauth_url."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": "zapier"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["oauth_url"] == ""  # no OAuth for webhook


# ===========================================================================
# OAuth callback + complete flow
# ===========================================================================

class TestOAuthComplete:

    async def test_callback_invalid_state(self, auth_headers):
        """Random/invalid state should be rejected."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "test_code_123", "state": "invalid_state_xyz"},
            )
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json().get("detail", "")

    async def test_callback_missing_params(self, auth_headers):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={},
            )
        assert resp.status_code == 400

    async def test_full_oauth_flow(self, auth_headers):
        """完整 OAuth 流程：start → callback → integration 建立（placeholder provider）。

        2026-09-15：原本用 google_calendar，但 google 有真 token endpoint，
        fake code 會被拒 → 502。改用 NOTION（未配置真 endpoint，走 placeholder 分支），
        呢個 flow 先真正測到「callback 成功建立 integration + tenant/user 綁定 + 列表可見」。
        """
        async with httpx.AsyncClient() as client:
            integration = await _oauth_connect(client, auth_headers, CONNECT_PROVIDER)

        assert integration["provider"] == CONNECT_PROVIDER
        assert integration["provider_display"] == CONNECT_PROVIDER_DISPLAY
        assert integration["status"] == "active"
        assert integration["tenant_id"] == KINETIX_TENANT
        assert integration["user_id"] == TEST_USER
        assert "config" in integration
        assert integration["config"]["access_token"].startswith("placeholder")
        assert "created_at" in integration
        assert "id" in integration

        # Step 3: Verify it shows up in the list
        async with httpx.AsyncClient() as client:
            list_resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations",
                headers=auth_headers,
            )
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["provider"] == CONNECT_PROVIDER

        return integration["id"]

    async def test_callback_exchange_provider_error_is_graceful(self, auth_headers):
        """有真 token endpoint 嘅 provider：provider 拒絕 fake code 時要 502，
        而且**唔可以**留低任何 integration row（唔可以有半連線狀態）。

        2026-09-15 新增：原本冇任何測試蓋住呢條 failure path。
        """
        async with httpx.AsyncClient() as client:
            start = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": TEST_PROVIDER},
            )
            assert start.status_code == 200
            state = start.json()["state"]

            cb = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "fake_code_rejected_by_provider", "state": state},
            )
            # 502 = 上游 provider 拒絕（唔係 500 crash）
            assert cb.status_code == 502, f"預期 502，實際 {cb.status_code} {cb.text[:120]}"
            assert "detail" in cb.json()

            # state 已用過 → 唔可以重玩
            replay = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "fake_code_rejected_by_provider", "state": state},
            )
            assert replay.status_code == 400

            lst = await client.get(f"{BACKEND_URL}/api/v1/integrations", headers=auth_headers)
        assert lst.status_code == 200
        assert lst.json() == [], "provider 失敗之後唔應該留低 integration"

    async def test_full_flow_with_all_providers(self, auth_headers):
        """全部 provider 行一次：placeholder 類要成功，真 endpoint 類要 graceful 502。"""
        async with httpx.AsyncClient() as client:
            # 1) 真 token endpoint 類：provider 拒絕 fake code → 502，唔留 row
            for provider in EXCHANGE_PROVIDERS:
                start = await client.post(
                    f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                    headers=auth_headers,
                    json={"provider": provider},
                )
                assert start.status_code == 200, f"start {provider} → {start.status_code}"
                cb = await client.post(
                    f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                    headers=auth_headers,
                    json={"code": f"code_{provider}", "state": start.json()["state"]},
                )
                assert cb.status_code in (500, 502), (
                    f"{provider} 應該 fail closed（500 = 未配置 / 502 = 上游拒絕），"
                    f"實際 {cb.status_code}"
                )

            # 2) placeholder 類：完整連線成功
            created_ids = []
            for provider in PLACEHOLDER_PROVIDERS:
                integ = await _oauth_connect(client, auth_headers, provider)
                assert integ["provider"] == provider
                assert integ["status"] == "active"
                created_ids.append(integ["id"])

            # 3) 列表只應該見到 placeholder 類（exchange 類冇留 row）
            list_resp = await client.get(f"{BACKEND_URL}/api/v1/integrations", headers=auth_headers)
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == len(PLACEHOLDER_PROVIDERS), f"實際 {len(items)} 個"
        assert {i["provider"] for i in items} == set(PLACEHOLDER_PROVIDERS)

        return created_ids


# ===========================================================================
# Integration CRUD
# ===========================================================================

class TestIntegrationCRUD:

    async def test_create_url_connection(self, auth_headers):
        """POST /integrations should create a URL-based connection directly."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/integrations",
                headers=auth_headers,
                json={
                    "provider": "google_calendar",
                    "provider_display": "Google Calendar",
                    "status": "active",
                    "config": {"connection_url": "https://calendar.google.com/calendar/ical/test/basic.ics"},
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["provider"] == "google_calendar"
        assert data["config"]["connection_url"] == "https://calendar.google.com/calendar/ical/test/basic.ics"
        assert data["status"] == "active"
        assert data["tenant_id"] == KINETIX_TENANT
        return data["id"]

    async def test_update_integration_status(self, auth_headers):
        """PATCH should update status and config."""
        # First create one
        async with httpx.AsyncClient() as client:
            # CONNECT_PROVIDER = placeholder path（真 endpoint 嘅 provider 會 502）
            integ_id = (await _oauth_connect(client, auth_headers, CONNECT_PROVIDER))["id"]

        # Update
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=auth_headers,
                json={"status": "error", "metadata_": {"last_error": "token_expired"}},
            )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["status"] == "error"
        assert updated["metadata_"]["last_error"] == "token_expired"

    async def test_delete_integration(self, auth_headers):
        """DELETE should remove the integration."""
        # Create one
        async with httpx.AsyncClient() as client:
            start = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": "slack"},
            )
            state = start.json()["state"]
            cb = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "code_slack", "state": state},
            )
        integ_id = cb.json()["id"]

        # Delete
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 204

        # Verify gone
        async with httpx.AsyncClient() as client:
            get_resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=auth_headers,
            )
        assert get_resp.status_code == 404

    async def test_get_single_integration(self, auth_headers):
        """GET by ID should return the full record."""
        # Create one
        async with httpx.AsyncClient() as client:
            integ_id = (await _oauth_connect(client, auth_headers, CONNECT_PROVIDER))["id"]

        # Get
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == integ_id
        assert data["provider"] == CONNECT_PROVIDER
        assert data["status"] == "active"


# ===========================================================================
# Tenant isolation — critical security test
# ===========================================================================

class TestTenantIsolation:

    async def test_cross_tenant_invisible(self, auth_headers, alt_auth_headers):
        """User A's integrations should be invisible to User B (different tenant)."""

        # User A creates an integration
        async with httpx.AsyncClient() as client:
            await _oauth_connect(client, auth_headers, CONNECT_PROVIDER)

        # User B (different tenant) should see nothing
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations",
                headers=alt_auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 0, "Cross-tenant data leak detected!"

    async def test_cross_tenant_get_blocked(self, auth_headers, alt_auth_headers):
        """User B should get 404 trying to access User A's integration by ID."""
        # Create as User A
        async with httpx.AsyncClient() as client:
            integ_id = (await _oauth_connect(client, auth_headers, CONNECT_PROVIDER))["id"]

        # User B tries to access User A's integration
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=alt_auth_headers,
            )
        assert resp.status_code == 404, "Cross-tenant read leak!"

        # User B tries to delete User A's integration
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{BACKEND_URL}/api/v1/integrations/{integ_id}",
                headers=alt_auth_headers,
            )
        assert resp.status_code == 404, "Cross-tenant delete leak!"


# ===========================================================================
# Error scenarios
# ===========================================================================

class TestErrorScenarios:

    async def test_duplicate_oauth_state_rejected(self, auth_headers):
        """Using the same OAuth state twice should fail."""
        async with httpx.AsyncClient() as client:
            start = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": CONNECT_PROVIDER},
            )
            state = start.json()["state"]

            # First use — OK
            cb1 = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "code_first", "state": state},
            )
            assert cb1.status_code == 200

            # Second use with same state — should fail (state was deleted)
            cb2 = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "code_second", "state": state},
            )
            assert cb2.status_code == 400

    async def test_expired_oauth_state_rejected(self, auth_headers, db_conn):
        """過期 OAuth state 唔可以再用（state 有 TTL，見 OAUTH_STATE_TTL_MIN）。

        2026-09-15 新增：之前 OAuthState 完全冇 expiry check → 洩漏咗嘅 state 可以
        無限期待用，未用嘅 state 亦一直累積（實測 300+ row）。
        """
        async with httpx.AsyncClient() as client:
            start = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/start",
                headers=auth_headers,
                json={"provider": CONNECT_PROVIDER},
            )
            assert start.status_code == 200
            state = start.json()["state"]

        # 將 created_at 推前到 TTL 之外
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE nexus_crm.nexus_oauth_states SET created_at = now() - interval '2 hours' "
                "WHERE state = %s",
                (state,),
            )
            assert cur.rowcount == 1, "應該搵到啱啱建立嘅 state"

        async with httpx.AsyncClient() as client:
            cb = await client.post(
                f"{BACKEND_URL}/api/v1/integrations/oauth/callback",
                headers=auth_headers,
                json={"code": "code_expired", "state": state},
            )
            assert cb.status_code == 400, f"過期 state 應該 400，實際 {cb.status_code}"

            lst = await client.get(f"{BACKEND_URL}/api/v1/integrations", headers=auth_headers)
        assert lst.json() == [], "過期 state 唔應該建立到 integration"

        # 清走呢條 state（test 自己嘅殘留）
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM nexus_crm.nexus_oauth_states WHERE state = %s", (state,))

    async def test_bad_integration_id_format(self, auth_headers):
        """Non-UUID string should be rejected gracefully."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/integrations/not-a-uuid",
                headers=auth_headers,
            )
        # FastAPI validates UUID path params — returns 422 or similar
        assert resp.status_code in (422, 404)
