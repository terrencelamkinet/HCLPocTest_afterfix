"""Test RLS isolation against the running backend."""

import pytest
import httpx
from jose import jwt

from app.config import settings
from app.services.auth_service import _load_private_key

BACKEND_URL = "http://localhost:8001"
KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def auth_headers():
    payload = {
        "sub": "9f3e7b11-e529-4cf8-82a6-2a62e4e5b643",
        "email": "terrence@kinetix.com",
        "role": "admin",
        "tenant_id": KINETIX_TENANT,
    }
    token = jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)
    return {"Authorization": f"Bearer {token}"}


class TestRLSIsolation:
    async def test_companies_isolated(self, auth_headers):
        """Authenticated user can access CRM data (even if empty)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/api/v1/crm/companies?limit=5",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        # RLS filters to tenant scope — items may be 0 if DB is empty
        assert isinstance(data["items"], list)

    async def test_unauthenticated_access_blocked(self):
        """Without auth, CRM data should be 403."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/api/v1/crm/companies")
        assert resp.status_code == 403
        assert "Tenant not identified" in resp.text

    async def test_health_public(self):
        """Health endpoint should be public."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
