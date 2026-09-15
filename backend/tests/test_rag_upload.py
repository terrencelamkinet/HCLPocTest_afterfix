"""T3 — 文件上載入知識庫：紅燈先行（未實作之前應該 fail / error）。

契約：
 1. PDF / txt 抽得到文字；唔支援嘅格式要有明確錯誤（唔可以靜默失敗）
 2. 抽唔到文字（例如空白 PDF / 掃描圖）要當錯誤 —— 唔可以留低半生半死嘅文件
 3. 敏感字串（password / token / API key）唔入索引內容
 4. 同一內容重複上載 → 偵測到（唔會重複入庫）
 5. 刪除文件之後唔再索引到
"""

import uuid

import pytest
from sqlalchemy import text

from app.ai.rag.ingest import (
    IngestError,
    content_hash,
    delete_file,
    extract_text,
    ingest_file,
    list_files,
    redact_sensitive,
)
from app.db import async_session

# 隨機 fake tenant（唔會撞真實 tenant 資料；測試自己收尾）
FAKE_TENANT = uuid.UUID("00000000-0000-0000-0000-00000000dead")


@pytest.fixture(autouse=True)
async def _dispose_db_engine():
    """每個 test 之後 dispose engine —— 避免 pytest-asyncio 換 event loop 之後
    用到上一個 loop 嘅 pooled connection（RuntimeError: Event loop is closed）。"""
    yield
    from app.db import engine
    await engine.dispose()


def _tiny_pdf(text_in: str = "PenguinCRM knowledge base test 2026") -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text_in)
    data = doc.tobytes()
    doc.close()
    return data


class TestExtraction:
    def test_pdf_text_extracted(self):
        assert "PenguinCRM" in extract_text(_tiny_pdf(), "doc.pdf")

    def test_txt_and_md_accepted(self):
        assert "hello knowledge" in extract_text(b"hello knowledge base test", "a.txt")
        assert "hello knowledge" in extract_text(b"hello knowledge base test", "a.md")

    def test_unsupported_format_rejected(self):
        with pytest.raises(IngestError) as e:
            extract_text(b"MZ\x90\x00binary", "virus.exe")
        assert "格式" in str(e.value)

    def test_blank_pdf_rejected(self):
        """空白 PDF（= 掃描圖情境）唔可以當成功入庫。"""
        import pymupdf as fitz

        doc = fitz.open()
        doc.new_page()
        data = doc.tobytes()
        doc.close()
        with pytest.raises(IngestError) as e:
            extract_text(data, "scan.pdf")
        assert "抽取唔到" in str(e.value) or "文字" in str(e.value)


class TestSensitiveData:
    def test_password_and_token_redacted(self):
        out = redact_sensitive("password: hunter2000 token=sk-abc123XYZ api_key: k-999")
        assert "hunter2000" not in out
        assert "sk-abc123XYZ" not in out
        assert "k-999" not in out

    def test_normal_text_untouched(self):
        s = "公司名：三六零數字安全；會議：2026年9月12日"
        assert redact_sensitive(s) == s


class TestHash:
    def test_same_content_same_hash(self):
        assert content_hash(b"abc") == content_hash(b"abc")
        assert content_hash(b"abc") != content_hash(b"abd")


@pytest.mark.asyncio
async def test_ingest_dedup_list_and_delete():
    """完整流程：上載 → 重複偵測 → 列出 → 刪除後唔再索引到。"""
    body = f"T3 知識庫測試文件 {uuid.uuid4()} 內容包含獨有片段".encode()
    async with async_session() as db:
        try:
            first = await ingest_file(
                db,
                tenant_id=FAKE_TENANT,
                workspace_id=FAKE_TENANT,
                user_id=None,
                filename="t3-test.txt",
                mime="text/plain",
                data=body,
            )
            assert first["status"] == "indexed", first
            assert first["chunks"] >= 1

            # 同一內容再上載 → duplicate，唔會多一份
            again = await ingest_file(
                db,
                tenant_id=FAKE_TENANT,
                workspace_id=FAKE_TENANT,
                user_id=None,
                filename="t3-test-copy.txt",
                mime="text/plain",
                data=body,
            )
            assert again["status"] == "duplicate", again
            assert again["file_id"] == first["file_id"]

            files = await list_files(db, tenant_id=FAKE_TENANT)
            assert len(files) == 1, files

            removed = await delete_file(
                db, tenant_id=FAKE_TENANT, file_id=uuid.UUID(first["file_id"])
            )
            assert removed == 1

            docs_left = (
                await db.execute(
                    text("""
                        SELECT count(*) FROM nexus_ai.vector_documents
                        WHERE tenant_id = :t AND source_module = 'file'
                    """),
                    {"t": FAKE_TENANT},
                )
            ).scalar()
            assert docs_left == 0, "刪除之後唔應該再有 file document"
            assert await list_files(db, tenant_id=FAKE_TENANT) == []
        finally:
            # 自清（唔留測試殘留）
            await db.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(FAKE_TENANT)}
            )
            await db.execute(
                text("DELETE FROM nexus_ai.vector_documents WHERE tenant_id = :t"),
                {"t": FAKE_TENANT},
            )
            await db.execute(
                text("DELETE FROM nexus_crm.files WHERE tenant_id = :t"), {"t": FAKE_TENANT}
            )
            await db.commit()
