"""Gemini provider adapter — google-genai SDK v2.

Registered as ``"gemini"``.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

from google import genai
from google.genai import types as genai_types

from app.ai.providers.base import (
    ProviderAdapter,
    UsageReport,
    compute_cost,
    register_provider,
)

_GEMINI_COST_CARDS: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "gemini-2.0-flash":         (Decimal("0.00010"), Decimal("0.00040"), Decimal("0")),
    "gemini-2.0-flash-lite":    (Decimal("0.000075"), Decimal("0.00030"), Decimal("0")),
    "gemini-2.5-pro":           (Decimal("0.00125"), Decimal("0.01000"), Decimal("0")),
    "gemini-2.5-flash":         (Decimal("0.00015"), Decimal("0.00060"), Decimal("0")),
    "gemini-1.5-pro":           (Decimal("0.00125"), Decimal("0.00500"), Decimal("0")),
    "gemini-1.5-flash":         (Decimal("0.000075"), Decimal("0.00030"), Decimal("0")),
}

# 2026-09-12 T1：embedding-001 已實證 404（Vertex frameshift-labs/us-central1）→ 剔除；
# gemini-embedding-001 可用（default 3072 維，可指定 1536 → 配合 vector(1536) schema）
_GEMINI_EMBEDDING_MODELS = {"gemini-embedding-001", "text-embedding-004"}

# 只有支援 matryoshka 降維嘅 model 可以指定輸出維度（text-embedding-004 固定 768）
_MODELS_WITH_OUTPUT_DIMS = {"gemini-embedding-001"}
DEFAULT_EMBED_MODEL = "gemini-embedding-001"
DEFAULT_EMBED_DIMS = 1536


@register_provider("gemini")
class GeminiAdapter(ProviderAdapter):
    """Adapter for Google Gemini models via google-genai SDK v2.

    Vertex AI mode（香港合法接入 — 2026-09-08 Terrence: external search 用 Gemini）:
    - 直接 ai.google.dev API 喺香港被 IP 封鎖 → 用 Vertex AI（GCP — asia-east1）。
    - 當 env ``VERTEX_PROJECT`` set → client = genai.Client(vertexai=True, ...) —
      credentials 用 GOOGLE_APPLICATION_CREDENTIALS（service account JSON）或者 ADC。
    - ``web_search()`` 用 Vertex Gemini 內置 Grounding with Google Search —
      external 問題（天氣/交通/新聞/知識）由 Gemini search 實時資料，唔使自己 maintain source。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "gemini-2.0-flash",
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._default_model = default_model
        # Vertex AI config（香港 — ai.google.dev 被封 → GCP Vertex）
        # 用 app settings（NEXUS_ prefix .env）— os.environ 唔會自動有 .env 值
        from app.config import settings

        self._vertex_project = settings.vertex_project.strip()
        self._vertex_location = settings.vertex_location.strip() or "us-central1"
        # Service account JSON — google-auth ADC 讀 GOOGLE_APPLICATION_CREDENTIALS env；
        # .env 唔 export → 喺呢度 setdefault 落 process env（ADC 先搵到）
        if settings.google_application_credentials and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
        self._client: Any = None  # lazy init

    def _make_client(self) -> Any:
        """Vertex AI mode 優先（有 VERTEX_PROJECT）；冇就 fallback api_key（dev 用）。"""
        if self._client is None:
            if self._vertex_project:
                # Vertex AI — credentials: GOOGLE_APPLICATION_CREDENTIALS JSON or ADC
                self._client = genai.Client(
                    vertexai=True,
                    project=self._vertex_project,
                    location=self._vertex_location,
                )
            else:
                self._client = genai.Client(api_key=self._api_key)
        return self._client

    @property
    def is_vertex(self) -> bool:
        return bool(self._vertex_project)

    async def web_search(self, query: str, model: str = "gemini-2.5-flash") -> tuple[str, list[str]]:
        """Gemini Grounding with Google Search（Vertex AI）— 實時 web search。

        Returns (answer_text, source_urls)。唔係 Vertex mode 或者失敗 → ("", []) —
        caller 自己 fallback（現有 briefing source / 內部知識）。
        """
        if not self._vertex_project:
            return "", []
        try:
            client = self._make_client()
            from google.genai import types as genai_types

            resp = await client.aio.models.generate_content(
                model=model,
                contents=query,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                    temperature=0.2,
                    max_output_tokens=900,
                ),
            )
            text = (resp.text or "").strip()
            urls: list[str] = []
            # Grounding metadata — search 來源 URL（如果 SDK expose）
            try:
                md = resp.candidates[0].grounding_metadata
                for chunk in (md.grounding_chunks or []):
                    u = getattr(chunk.web, "uri", "")
                    if u and u not in urls:
                        urls.append(u)
            except Exception:
                pass
            return text, urls[:5]
        except Exception:
            return "", []

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, UsageReport]:
        resolved = model or self._default_model

        # Convert OpenAI-style messages to Gemini content list
        contents = _to_gemini_contents(messages)

        kwargs: dict[str, Any] = dict(
            model=resolved,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        response = self._make_client().models.generate_content(**kwargs)
        text = response.text or ""

        usage = response.usage_metadata
        report = UsageReport(
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            cost_usd=_gemini_cost(resolved, usage),
            model=resolved,
            provider="gemini",
        )
        return text, report

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, UsageReport]]:
        resolved = model or self._default_model
        contents = _to_gemini_contents(messages)

        stream = self._make_client().models.generate_content_stream(
            model=resolved,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        final_usage = None
        for chunk in stream:
            if chunk.text:
                yield chunk.text, UsageReport()
            if chunk.usage_metadata:
                final_usage = chunk.usage_metadata

        report = UsageReport(
            input_tokens=final_usage.prompt_token_count if final_usage else 0,
            output_tokens=final_usage.candidates_token_count if final_usage else 0,
            cost_usd=_gemini_cost(resolved, final_usage),
            model=resolved,
            provider="gemini",
        )
        yield "", report

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        model: str = DEFAULT_EMBED_MODEL,
        output_dimensionality: int = DEFAULT_EMBED_DIMS,
    ) -> tuple[list[list[float]], UsageReport]:
        m = model or DEFAULT_EMBED_MODEL
        kwargs: dict[str, Any] = {"model": m, "contents": texts}
        # gemini-embedding-001 default = 3072 維 → 唔指定輸出維度會同 vector(1536) schema 撞
        if m in _MODELS_WITH_OUTPUT_DIMS and output_dimensionality:
            from google.genai import types as genai_types
            kwargs["config"] = genai_types.EmbedContentConfig(
                output_dimensionality=output_dimensionality
            )
        result = self._make_client().models.embed_content(**kwargs)
        vectors = [e.values for e in result.embeddings]
        report = UsageReport(
            input_tokens=sum(len(t.split()) for t in texts),
            model=model,
            provider="gemini",
        )
        return vectors, report


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _to_gemini_contents(messages: list[dict[str, Any]]) -> list[genai_types.Content]:
    """Convert OpenAI-format messages to Gemini Content list."""
    role_map = {"user": "user", "assistant": "model", "system": "user"}
    contents: list[genai_types.Content] = []
    for msg in messages:
        role = role_map.get(msg.get("role", "user"), "user")
        content = msg.get("content", "")
        if not content:
            continue
        # Prepend "System: " for system messages so Gemini understands
        prefix = "System instruction: " if msg.get("role") == "system" else ""
        contents.append(genai_types.Content(
            role=role,
            parts=[genai_types.Part(text=prefix + content)],
        ))
    return contents


def _gemini_cost(model: str, usage: Any) -> Decimal:
    """Compute Gemini cost from usage_metadata."""
    if usage is None:
        return Decimal("0")
    card = _GEMINI_COST_CARDS.get(model)
    if card is None:
        # Linear search fallback
        for key, c in _GEMINI_COST_CARDS.items():
            if model.startswith(key):
                card = c
                break
    if card is None:
        return Decimal("0")

    inp = usage.prompt_token_count or 0
    out = usage.candidates_token_count or 0
    total = (inp * card[0] + out * card[1]) / Decimal("1000")
    return total.quantize(Decimal("0.000001"))
