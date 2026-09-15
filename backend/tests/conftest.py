"""共用 test fixtures。

2026-09-15：test_integrations.py / test_whatsapp.py 嘅 tenant isolation case 一直
假設 DB 已經有第二個 tenant（...0002）同 ALT_USER，但實際上從來冇 seed 過任何嘢。
`app/db.py:66` 嘅 T4 defence（token 嘅 tenant 唔存在 → 401）令嗰批 test 一直紅。

呢度 idempotent 補齊（`ON CONFLICT DO NOTHING`），令 test suite 自給自足：
唔會覆蓋、唔會刪任何現有 row；跑幾多次結果一樣。
"""
from __future__ import annotations

import re

import pytest

KINETIX_TENANT = "00000000-0000-0000-0000-000000000001"
ALT_TENANT = "00000000-0000-0000-0000-000000000002"
TEST_USER = "9f3e7b11-e529-4cf8-82a6-2a62e4e5b643"
ALT_USER = "aaaaaaaa-e529-4cf8-82a6-2a62e4e5bbbb"

_TENANTS = [
    (KINETIX_TENANT, "Kinetix", "kinetix"),
    (ALT_TENANT, "ALT Test Tenant", "alt-test-tenant"),
]

_USERS = [
    # email 用 .local 合成域名：test@test.com / alt@test.com 喺 DB 已經屬於其他 user id，
    # 用返會撞 email unique index → ON CONFLICT DO NOTHING 靜默跳過 → 之後 FK 爆。
    (TEST_USER, "test.fixture.user@nexus.local", "Test User"),
    (ALT_USER, "alt.fixture.user@nexus.local", "ALT Test User"),
]


def _dsn() -> str:
    """直接連 DB；由 app config（= backend/.env）讀。

    nexus_auth.* 三張表嘅 owner 係 gg_fighter（= settings.database_url），只有佢有
    INSERT/UPDATE 權；nexus_app 同 nexus_admin 都得 SELECT，所以 provision 必須用
    gg_fighter。唔會改任何現有 row（全部 ON CONFLICT DO NOTHING）。
    """
    from app.config import settings

    url = settings.database_url or settings.app_database_url
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


@pytest.fixture(scope="session")
def seeded_test_tenants():
    """確保 isolation test 需要嘅 tenant / user / membership 存在。"""
    import psycopg2

    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for tid, name, sub in _TENANTS:
                cur.execute(
                    """
                    INSERT INTO nexus_auth.nexus_auth_tenants
                        (id, name, subdomain, settings, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, '{}'::json, true, now(), now())
                    ON CONFLICT DO NOTHING
                    """,
                    (tid, name, sub),
                )
            for uid, email, display in _USERS:
                cur.execute(
                    """
                    INSERT INTO nexus_auth.nexus_auth_users
                        (id, email, password_hash, display_name, email_verified,
                         mfa_enabled, role, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, true, false, 'admin', now(), now())
                    ON CONFLICT DO NOTHING
                    """,
                    (uid, email, "test-fixture-not-a-real-hash", display),
                )

            # seed 完要驗：唔可以靜默失敗（例如 email 撞 unique index），
            # 否則之後嘅 FK violation 會完全睇唔出係 seed 問題。
            cur.execute(
                "SELECT id FROM nexus_auth.nexus_auth_tenants WHERE id = ANY(%s::uuid[])",
                ([t[0] for t in _TENANTS],),
            )
            have_t = {str(r[0]) for r in cur.fetchall()}
            missing_t = {t[0] for t in _TENANTS} - have_t
            assert not missing_t, f"tenant seed 失敗：{missing_t}"

            cur.execute(
                "SELECT id FROM nexus_auth.nexus_auth_users WHERE id = ANY(%s::uuid[])",
                ([u[0] for u in _USERS],),
            )
            have_u = {str(r[0]) for r in cur.fetchall()}
            missing_u = {u[0] for u in _USERS} - have_u
            assert not missing_u, f"user seed 失敗（email 撞其他 row？）：{missing_u}"
            for tid, uid in ((KINETIX_TENANT, TEST_USER), (ALT_TENANT, ALT_USER)):
                cur.execute(
                    """
                    INSERT INTO nexus_auth.nexus_auth_tenant_members
                        (id, tenant_id, user_id, role, created_at)
                    SELECT gen_random_uuid(), %s::uuid, %s::uuid, 'admin', now()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM nexus_auth.nexus_auth_tenant_members
                        WHERE tenant_id = %s::uuid AND user_id = %s::uuid
                    )
                    """,
                    (tid, uid, tid, uid),
                )
    finally:
        conn.close()
    yield


@pytest.fixture
def db_conn():
    """psycopg2 連線（gg_fighter = nexus_* 表 owner），俾 test 直接 seed / 驗 DB。

    autocommit：test 自己要清乾淨自己寫嘅嘢。
    """
    import psycopg2

    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()
