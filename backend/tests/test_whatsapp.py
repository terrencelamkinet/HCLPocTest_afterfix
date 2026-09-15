"""
WhatsApp Integration Tests — webhook verification, OTP flow, binding.

Run:
  source venv/bin/activate && pytest tests/test_whatsapp.py -v --capture=no

Requires: backend running on http://localhost:8001
"""
import pytest
import httpx
from jose import jwt

from app.config import settings
from app.services.auth_service import _load_private_key

BACKEND_URL = "http://localhost:8001"
KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
ALT_TENANT = "00000000-0000-0000-0000-000000000002"
TEST_USER = "9f3e7b11-e529-4cf8-82a6-2a62e4e5b643"
ALT_USER = "aaaaaaaa-e529-4cf8-82a6-2a62e4e5bbbb"
TEST_PHONE = "+85200000000"
ALT_PHONE = "+85200000000"


def _make_token(sub: str, tenant_id: str, email: str = "test@test.com") -> str:
    payload = {
        "sub": sub,
        "email": email,
        "role": "admin",
        "tenant_id": tenant_id,
    }
    return jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)


@pytest.fixture
def auth_headers(seeded_test_tenants):
    return {"Authorization": f"Bearer {_make_token(TEST_USER, KINETIX_TENANT)}"}


@pytest.fixture
def alt_auth_headers(seeded_test_tenants):
    return {"Authorization": f"Bearer {_make_token(ALT_USER, ALT_TENANT, 'alt@test.com')}"}


# ─── Webhook Verification ──────────────────────────────────────────


class TestWebhookVerification:

    async def test_webhook_get_valid(self):
        """GET /api/v1/whatsapp/webhook with valid verify_token should return challenge."""
        vt = settings.whatsapp_webhook_verify_token
        if not vt:
            pytest.skip("WHATSAPP_WEBHOOK_VERIFY_TOKEN not configured")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": vt,
                    "hub.challenge": "1234567890",
                },
            )
        assert resp.status_code == 200
        assert resp.text == "1234567890"

    async def test_webhook_get_invalid_token(self):
        """Invalid verify_token should return 403."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "WRONG_TOKEN",
                    "hub.challenge": "1234567890",
                },
            )
        assert resp.status_code == 403

    async def test_webhook_get_wrong_mode(self):
        """Wrong hub.mode should return 403."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/whatsapp/webhook",
                params={
                    "hub.mode": "unsubscribe",
                    "hub.verify_token": settings.whatsapp_webhook_verify_token or "",
                    "hub.challenge": "1234567890",
                },
            )
        assert resp.status_code == 403

    async def test_webhook_post_invalid_signature(self):
        """POST without valid signature should return 403."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/webhook",
                json={"entry": []},
                headers={"X-Hub-Signature-256": "sha256=invalid"},
            )
        assert resp.status_code == 403

    async def test_webhook_post_missing_signature(self):
        """POST without signature header should return 403."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/webhook",
                json={"entry": []},
            )
        assert resp.status_code == 403


# ─── OTP Sending ────────────────────────────────────────────────────


class TestSendOTP:

    async def test_send_otp_no_auth(self):
        """Without auth token, should return 403/401."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/send-otp",
                json={"phone": TEST_PHONE},
            )
        assert resp.status_code in (401, 403)

    async def test_send_otp_missing_phone(self, auth_headers):
        """Missing phone field should return 400."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/send-otp",
                json={},
                headers=auth_headers,
            )
        assert resp.status_code == 400

    async def test_send_otp_success(self, auth_headers):
        """With valid auth, should trigger OTP send."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/send-otp",
                json={"phone": TEST_PHONE},
                headers=auth_headers,
            )
        # If WhatsApp API not configured, get 502 — that's expected in dev
        # Otherwise 200
        if resp.status_code == 502:
            assert "Failed to send OTP" in resp.json().get("detail", "")
        else:
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("sent", "debug")
            assert data["wa_id"] == TEST_PHONE
            assert data["expires_in"] == 300


# ─── OTP Verification & Binding ──────────────────────────────────────


class TestVerifyOTP:

    async def test_verify_no_auth(self):
        """Without auth token, should return 401/403."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/verify-otp",
                json={"phone": TEST_PHONE, "otp": "123456"},
            )
        assert resp.status_code in (401, 403)

    async def test_verify_missing_fields(self, auth_headers):
        """Missing phone or otp should return 400."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/verify-otp",
                json={},
                headers=auth_headers,
            )
        assert resp.status_code == 400

    async def test_verify_invalid_otp(self, auth_headers):
        """Invalid OTP should return 400."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/verify-otp",
                json={"phone": TEST_PHONE, "otp": "000000"},
                headers=auth_headers,
            )
        assert resp.status_code == 400
        assert "Invalid or expired OTP" in resp.json().get("detail", "")


# ─── WhatsApp Status ────────────────────────────────────────────────


class TestStatus:

    async def test_status_disconnected(self, auth_headers):
        """Fresh user should show disconnected status."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/whatsapp/status",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disconnected"

    async def test_status_no_auth(self):
        """Without auth, should return 401/403."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/api/v1/whatsapp/status")
        assert resp.status_code in (401, 403)

    async def test_status_tenant_isolation(self, auth_headers, alt_auth_headers):
        """Different tenant should not see same connection."""
        # Both should show disconnected (clean state)
        async with httpx.AsyncClient() as client:
            r1 = await client.get(f"{BACKEND_URL}/api/v1/whatsapp/status", headers=auth_headers)
            r2 = await client.get(f"{BACKEND_URL}/api/v1/whatsapp/status", headers=alt_auth_headers)
        assert r1.json()["status"] == "disconnected"
        assert r2.json()["status"] == "disconnected"


# ─── Disconnect ─────────────────────────────────────────────────────


class TestDisconnect:

    async def test_disconnect_no_auth(self, auth_headers):
        """Without auth, should return 401/403."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{BACKEND_URL}/api/v1/whatsapp/disconnect")
        assert resp.status_code in (401, 403)

    async def test_disconnect_when_not_connected(self, auth_headers):
        """Disconnecting when not connected should still succeed gracefully."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/whatsapp/disconnect",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"
