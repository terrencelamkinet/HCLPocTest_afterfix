"""DLP（Data Loss Prevention）— 紅燈先行。

設計取捨（刻意）：
  - **只捉真敏感**：secrets（password/token/api key）、HKID、信用卡號
  - **唔捉電話號碼** —— CRM 正常資料滿佈電話，捉咗 = 全部 flag，等於冇用（噪音）
  - 出站邊界（餵去 LLM 嘅內容）掃 → 命中：遮蔽 + 寫審計（`dlp.flagged`）
  - 審計**唔記原文**：只記類型 + 位置數目 + 來源

契約：
 1. 捉得到 secrets / HKID / 信用卡
 2. 正常 CRM 文字零命中（唔可以誤報）
 3. 遮蔽保留結構（label 留低，值走）
 4. 命中要寫審計 row（`ai_audit_log`，event_type=dlp.flagged）
 5. RAG context 出站前要掃 + 遮蔽（整合證明）
"""

import uuid

import pytest
from sqlalchemy import text

from app.db import async_session
from app.services.dlp import DlpVerdict, redact_text, scan_text

T = uuid.UUID("00000000-0000-0000-0000-0000000d1001")
USER = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

# ⚠️ 測試用嘅假 secret 要 runtime 砌 —— 唔可以喺檔案寫成一個完整 credential 樣嘅字面值。
# 2026-09-12 踩過：write 檔時 tooling 會自動遮蔽 credential 樣字串 → 檔內變成 `***`
# （3 個字）→ 唔夠 regex 要求嘅 4 字 → 測試假失敗，查咗一輪。
def _fake_token() -> str:
    return "tok" + "_" + "a1b2c3d4"


FAKE_TOKEN = _fake_token()


@pytest.fixture(autouse=True)
async def _db_fixture():
    """一個 fixture 搞掂：**開始前**先 dispose engine（清走上一個 test 嘅 event loop
    留低嘅 pooled connection —— 唔清就會 `RuntimeError: Event loop is closed`），
    之後清測試資料、再 dispose。"""
    from app.db import engine

    await engine.dispose()
    yield
    try:
        async with async_session() as db:
            await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
            await db.execute(text("DELETE FROM nexus_ai.ai_audit_log WHERE tenant_id = :t"), {"t": T})
            await db.execute(text("DELETE FROM nexus_ai.vector_documents WHERE tenant_id = :t"), {"t": T})
            # ⚠️ 一定要清 files —— 唔清嘅話下一輪 ingest 會 dedup 命中（content_hash）
            # 返 'duplicate' 而唔係 'indexed'，測試就會假失敗（2026-09-12 踩過）
            await db.execute(text("DELETE FROM nexus_crm.files WHERE tenant_id = :t"), {"t": T})
            await db.commit()
    except Exception:
        pass
    await engine.dispose()


def test_detects_secrets_hkid_and_card():
    text_in = (
        "登入資料 password: hunter2000，API key: sk-live-abc123XYZ，"
        "客戶身份證 A123456(3)，信用卡 4111 1111 1111 1111。"
    )
    v = scan_text(text_in)
    assert isinstance(v, DlpVerdict)
    assert v.hit is True, "應該捉到敏感資料"
    labels = {h.label for h in v.hits}
    assert "secret" in labels
    assert "hkid" in labels
    assert "credit_card" in labels


def test_benign_crm_text_has_no_hits():
    benign = (
        "公司：三六零數字安全國際有限公司；聯絡人：陳大文；"
        "電話：2865 4321；跟進：2026年9月12日開會討論退款政策。"
    )
    v = scan_text(benign)
    assert v.hit is False, f"正常 CRM 文字唔應該誤報：{v.hits}"


def test_redact_preserves_label_and_removes_value():
    text_in = "password: hunter2000"
    out = redact_text(text_in)
    assert "hunter2000" not in out, "值一定要走"
    assert "password" in out.lower(), "label 要留低（俾人知係咩被遮）"
    assert "[REDACTED" in out.upper()


def test_redact_is_noop_when_clean():
    benign = "公司：CK Hutchison；跟進：下星期再傾"
    assert redact_text(benign) == benign


@pytest.mark.asyncio
async def test_write_audit_event():
    from app.services.dlp import audit_dlp

    v = scan_text("token: sk-test-999")
    assert v.hit
    async with async_session() as db:
        await audit_dlp(db, tenant_id=T, user_id=USER, verdict=v, source="rag_context")
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        rows = (await db.execute(text(
            "SELECT event_type, detail FROM nexus_ai.ai_audit_log WHERE tenant_id = :t"), {"t": T})).mappings().all()
    assert len(rows) == 1, rows
    assert rows[0]["event_type"] == "dlp.flagged"
    d = rows[0]["detail"]
    assert d.get("hit_labels"), d
    # 審計唔准記原文
    assert "sk-test-999" not in str(d), "審計唔可以記原文"


def test_outbound_raw_secret_is_redacted():
    """出站邊界直接掃一段未經 ingest 嘅文字 → 值一定要走（DLP 本身嘅保證）。"""
    raw = f"公司備註：token: {FAKE_TOKEN}；跟進：下星期再傾"
    assert scan_text(raw).hit
    out = redact_text(raw)
    assert FAKE_TOKEN not in out, "出站文字嘅值一定要被遮"
    assert "token" in out.lower(), "label 要保留"


@pytest.mark.asyncio
async def test_rag_context_never_leaks_plaintext_and_is_flagged():
    """整合：CRM 記錄衍生嘅 chunk 含明文 secret → retrieve_context 出站前遮蔽 + dlp.flagged。

    ⚠️ 刻意**唔行 ingest 路徑**：上載文件時 ingest 層已經遮咗敏感字（`[已遮蔽]`），
    所以條條路都搵唔到嘢。DLP 出站層嘅價值正正係覆蓋 **CRM 記錄衍生內容**
    （`reindex.py` 直接將 companies/contacts/tasks 文字入向量庫，冇經 ingest 遮蔽）。
    """
    from app.ai.rag.search import embed_texts, retrieve_context

    secret_text = f"Company: 三六零數字安全 Notes: 系統登入 token: {FAKE_TOKEN} 請聯絡 IT 部門"
    async with async_session() as db:
        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        doc_id = uuid.uuid4()
        vec = (await embed_texts([secret_text]))[0]
        await db.execute(
            text("""
                INSERT INTO nexus_ai.vector_documents
                    (id, tenant_id, workspace_id, visibility_scope, source_module,
                     source_record_id, created_at)
                VALUES (:id, :t, :t, 'workspace', 'company', :rec, now())
            """),
            {"id": doc_id, "t": T, "rec": uuid.uuid4()},
        )
        await db.execute(
            text("""
                INSERT INTO nexus_ai.vector_document_chunks
                    (id, document_id, chunk_text, embedding, tenant_id, workspace_id, visibility_scope)
                VALUES (:id, :doc, :txt, CAST(:vec AS vector), :t, :t, 'workspace')
            """),
            {"id": uuid.uuid4(), "doc": doc_id, "txt": secret_text, "vec": str(vec), "t": T},
        )
        await db.commit()

        ctx = await retrieve_context(
            db, query="系統登入 token", tenant_id=T, user_id=USER, min_score=0.2,
        )
        assert ctx, "應該檢索到 CRM 記錄 chunk"
        assert FAKE_TOKEN not in ctx, "餵去 LLM 嘅 context 唔可以有明文 secret（DLP 出站層負責）"
        assert "[REDACTED" in ctx, f"應該有 DLP 遮蔽標記：{ctx[:200]!r}"

        await db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(T)})
        events = [r[0] for r in (await db.execute(text(
            "SELECT event_type FROM nexus_ai.ai_audit_log WHERE tenant_id = :t"), {"t": T})).all()]
        assert "dlp.flagged" in events, f"應該寫 DLP 審計，實際 {events}"
