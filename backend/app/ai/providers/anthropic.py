"""Anthropic provider adapter.

Uses the ``anthropic`` async SDK.  Requires ``ANTHROPIC_API_KEY`` in env
or an explicit ``api_key`` kwarg.

Registered as ``"anthropic"`` in the provider registry.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, Optional

from anthropic import AsyncAnthropic

from app.ai.providers.base import (
    ProviderAdapter,
    UsageReport,
    compute_cost,
    register_provider,
)


@register_provider("anthropic")
class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic Claude messages API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._client = AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=base_url,
        )
        self._default_model = default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, UsageReport]:
        resolved_model = model or self._default_model
        kwargs: dict[str, Any] = dict(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)
        content = "".join(b.text for b in response.content if b.type == "text")

        usage = response.usage
        report = UsageReport(
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cached_input_tokens=usage.cache_read_input_tokens if usage and hasattr(usage, "cache_read_input_tokens") else 0,
            cost_usd=compute_cost(
                resolved_model,
                usage.input_tokens if usage else 0,
                usage.output_tokens if usage else 0,
                usage.cache_read_input_tokens if usage and hasattr(usage, "cache_read_input_tokens") else 0,
            ),
            model=resolved_model,
            provider="anthropic",
        )
        return content, report

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, UsageReport]]:
        resolved_model = model or self._default_model
        async with self._client.messages.stream(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ) as stream:
            final_usage = None
            async for text in stream.text_stream:
                yield text, UsageReport()  # partial

            response = await stream.get_final_message()
            usage = response.usage
            final_usage = UsageReport(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cached_input_tokens=usage.cache_read_input_tokens if usage and hasattr(usage, "cache_read_input_tokens") else 0,
                cost_usd=compute_cost(
                    resolved_model,
                    usage.input_tokens if usage else 0,
                    usage.output_tokens if usage else 0,
                    usage.cache_read_input_tokens if usage and hasattr(usage, "cache_read_input_tokens") else 0,
                ),
                model=resolved_model,
                provider="anthropic",
            )
            yield "", final_usage

    async def embed(
        self,
        texts: list[str],
        model: str = "",
    ) -> tuple[list[list[float]], UsageReport]:
        raise NotImplementedError("Anthropic does not yet expose a public embedding API.")

    async def close(self) -> None:
        await self._client.close()
