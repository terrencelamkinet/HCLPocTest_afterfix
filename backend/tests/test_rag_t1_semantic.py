"""T1 — 語意檢索：紅燈先行（未實作之前呢個檔案應該全部 fail）。

三個行為契約：
 1. embed_query 必須優先語意模型，local tf-idf 只可以做最後 fallback
 2. gemini embed 必須明確要求 1536 維（唔可以跟 model default，否則會撞 vector(1536) schema）
 3. Gemini embedding allowlist 唔准留住已 404 嘅死 model
"""

import pytest

from app.ai.rag import search as rag_search
from app.ai.providers.base import get_provider, UsageReport


class _FakeAdapter:
    """Spy adapter — 回傳固定 marker，並記錄被叫嘅 model。"""

    def __init__(self, marker: float = 0.25):
        self.marker = marker
        self.calls: list[str] = []

    async def embed(self, texts, model=None):
        self.calls.append(str(model))
        return (
            [[self.marker] * 1536 for _ in texts],
            UsageReport(input_tokens=1, model=str(model), provider="gemini"),
        )

    async def close(self):  # provider adapter contract
        return None


@pytest.mark.asyncio
async def test_embed_query_prefers_semantic_over_local(monkeypatch):
    """語意模型優先；local tf-idf 唔可以再搶先（現行 priority 1 = local → RED）。"""

    def fake_local(texts):
        # 明顯唔同嘅 marker，方便分辨邊個贏
        return [[0.5] * 1536 for _ in texts]

    monkeypatch.setattr("app.ai.rag.local_embed.local_embed", fake_local)

    spy = _FakeAdapter(marker=0.25)
    monkeypatch.setattr(rag_search, "get_provider", lambda name: spy)

    vec = await rag_search.embed_query("客戶會議跟進事項")

    assert vec[0] == pytest.approx(0.25), (
        "語意模型應該贏過 local tf-idf，實際拎到嘅係 "
        f"{'local tf-idf 嘅向量' if vec[0] == pytest.approx(0.5) else '未知來源'}"
    )
    assert spy.calls, "語意 provider 應該真係被叫過"


@pytest.mark.asyncio
async def test_gemini_embed_requests_1536_dims(monkeypatch):
    """gemini embed 必須帶 output_dimensionality=1536（現行冇帶 → RED）。"""
    adapter = get_provider("gemini")

    captured: dict = {}

    class _FakeModels:
        def embed_content(self, **kwargs):
            captured.update(kwargs)

            class _E:
                values = [0.1] * 1536

            class _R:
                embeddings = [_E()]

            return _R()

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(adapter, "_make_client", lambda: _FakeClient())

    _vecs, _report = await adapter.embed(["測試"])

    cfg = captured.get("config")
    dims = getattr(cfg, "output_dimensionality", None)
    assert dims == 1536, (
        "embed 必須指定 1536 維（gemini-embedding-001 default = 3072，"
        f"唔指定就會同 vector(1536) schema 撞；實際 = {dims}）"
    )


def test_embedding_allowlist_has_no_dead_model():
    """embedding-001 已實證 404，唔准留喺 allowlist；要加返可用嘅 gemini-embedding-001。"""
    from app.ai.providers.gemini import _GEMINI_EMBEDDING_MODELS

    assert "embedding-001" not in _GEMINI_EMBEDDING_MODELS
    assert "gemini-embedding-001" in _GEMINI_EMBEDDING_MODELS
