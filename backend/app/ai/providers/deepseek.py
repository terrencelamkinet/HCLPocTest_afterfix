"""DeepSeek provider adapter — OpenAI-compatible API via custom base_url.

Registered as ``"deepseek"``.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI

from app.ai.providers.base import (
    ProviderAdapter,
    UsageReport,
    compute_cost,
    register_provider,
)

_DEEPSEEK_COST_CARDS: dict[str, tuple[Decimal, Decimal]] = {
    "deepseek-chat":     (Decimal("0.00027"), Decimal("0.00110")),
    "deepseek-reasoner": (Decimal("0.00055"), Decimal("0.00219")),
}


@register_provider("deepseek")
class DeepSeekAdapter(ProviderAdapter):
    """Adapter for DeepSeek models via OpenAI-compatible API."""

    BASE_URL = "https://api.deepseek.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "deepseek-chat",
    ) -> None:
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._client = AsyncOpenAI(api_key=key, base_url=self.BASE_URL)
        self._default_model = default_model

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
        kwargs: dict[str, Any] = dict(
            model=resolved,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""

        usage = response.usage
        report = UsageReport(
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost_usd=_deepseek_cost(resolved, usage),
            model=resolved,
            provider="deepseek",
        )
        return content, report

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, UsageReport]]:
        resolved = model or self._default_model
        stream = await self._client.chat.completions.create(
            model=resolved,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )

        full_content: list[str] = []
        final_usage = None
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                full_content.append(delta.content)
                yield delta.content, UsageReport()
            if chunk.usage:
                final_usage = chunk.usage

        report = UsageReport(
            input_tokens=final_usage.prompt_tokens if final_usage else 0,
            output_tokens=final_usage.completion_tokens if final_usage else 0,
            cost_usd=_deepseek_cost(resolved, final_usage),
            model=resolved,
            provider="deepseek",
        )
        yield "", report

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, list[dict[str, Any]], UsageReport]:
        """Chat with function calling — DeepSeek is OpenAI-compatible so we
        forward `tools` and surface message.tool_calls (2026-09-09)."""
        resolved = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=resolved,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls: list[dict[str, Any]] = []
        if getattr(choice.message, "tool_calls", None):
            tool_calls = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        usage = response.usage
        report = UsageReport(
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cost_usd=_deepseek_cost(resolved, usage),
            model=resolved,
            provider="deepseek",
        )
        return content, tool_calls, report

    # ------------------------------------------------------------------
    # Embed — not supported by DeepSeek
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        model: str = "",
    ) -> tuple[list[list[float]], UsageReport]:
        raise NotImplementedError("DeepSeek does not support embeddings")


def _deepseek_cost(model: str, usage: Any) -> Decimal:
    if usage is None:
        return Decimal("0")
    card = _DEEPSEEK_COST_CARDS.get(model)
    if card is None:
        return Decimal("0")
    inp = usage.prompt_tokens or 0
    out = usage.completion_tokens or 0
    total = (inp * card[0] + out * card[1]) / Decimal("1000")
    return total.quantize(Decimal("0.000001"))
