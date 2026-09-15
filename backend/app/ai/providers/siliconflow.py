"""SiliconFlow provider adapter — OpenAI-compatible API.

Registered as ``"siliconflow"``. Used as the failover provider for the
default tenant model profile (nexus_ai.model_profiles.fallback_provider =
'siliconflow'), so a DeepSeek outage degrades to Qwen instead of erroring.

The API surface is identical to DeepSeek's (OpenAI-compatible), so this
adapter mirrors ``DeepSeekAdapter`` with a different base_url / key / provider
tag. SiliconFlow pricing is not in the central cost cards → recorded cost 0.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI

from app.ai.providers.base import (
    ProviderAdapter,
    UsageReport,
    register_provider,
)

_SILICONFLOW_BASE_URL = os.environ.get(
    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
)


def _resolve_key() -> str:
    """Prefer the G08 provider-key store, fall back to env."""
    try:
        from app.services.provider_keys import cached_provider_key

        key = cached_provider_key("siliconflow")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("SILICONFLOW_API_KEY", "")


@register_provider("siliconflow")
class SiliconFlowAdapter(ProviderAdapter):
    """Adapter for SiliconFlow-hosted models (Qwen, GLM, ...)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "Qwen/Qwen3-30B-A3B-Instruct-2507",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key or _resolve_key(),
            base_url=_SILICONFLOW_BASE_URL,
        )
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
            cost_usd=Decimal("0"),  # SiliconFlow pricing not in cost cards
            model=resolved,
            provider="siliconflow",
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

        final_usage = None
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content, UsageReport()
            if chunk.usage:
                final_usage = chunk.usage

        report = UsageReport(
            input_tokens=final_usage.prompt_tokens if final_usage else 0,
            output_tokens=final_usage.completion_tokens if final_usage else 0,
            cost_usd=Decimal("0"),
            model=resolved,
            provider="siliconflow",
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
        """OpenAI-compatible function calling (forwarded tools)."""
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
            cost_usd=Decimal("0"),
            model=resolved,
            provider="siliconflow",
        )
        return content, tool_calls, report

    # ------------------------------------------------------------------
    # Embed — not used for chat failover
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        model: str = "",
    ) -> tuple[list[list[float]], UsageReport]:
        raise NotImplementedError("SiliconFlow embeddings not wired")
