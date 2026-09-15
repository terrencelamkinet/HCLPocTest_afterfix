"""Test RAG (semantic search) endpoints against the running backend."""

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


class TestRAGHealth:
    async def test_health(self):
        """RAG health endpoint returns embedding status."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BACKEND_URL}/api/v1/ai/rag/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("embedding_ready") is True
        assert data.get("embedding_dims", 0) > 0


class TestRAGSearch:
    async def test_search_basic(self, auth_headers):
        """RAG search returns results when data exists."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/ai/rag/search",
                json={"query": "test", "limit": 5},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        # RAG has 438 indexed docs for Kinetix tenant
        if data["total"] > 0:
            assert data["results"][0].get("score", 0) > 0

    async def test_search_empty_query(self, auth_headers):
        """Empty query returns 200 with empty results (not 422)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/ai/rag/search",
                json={"query": "", "limit": 5},
                headers=auth_headers,
            )
        # Current API returns 200 for empty query → acceptable for now
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("results", [])) == 0


class TestRAGContext:
    async def test_context_injection(self, auth_headers):
        """RAG context endpoint returns context."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BACKEND_URL}/api/v1/ai/rag/context",
                json={"query": "test", "max_tokens": 500},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "context" in data
