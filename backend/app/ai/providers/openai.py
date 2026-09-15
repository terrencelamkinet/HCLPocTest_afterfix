"""OpenAI provider adapter.

Uses the ``openai`` async client.  Requires ``OPENAI_API_KEY`` in env
or an explicit ``api_key`` kwarg.

Registered as ``"openai"`` in the provider registry.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI

from app.ai.providers.base import (
    ProviderAdapter,
    UsageReport,
    compute_cost,
    register_provider,
)


@register_provider("openai")
class OpenAIAdapter(ProviderAdapter):
    """Adapter for OpenAI chat completion + embedding APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        default_model: str = "gpt-4o",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            organization=organization,
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
            cached_input_tokens=usage.prompt_tokens_details.cached_tokens if usage and usage.prompt_tokens_details else 0,
            cost_usd=compute_cost(
                resolved_model,
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
                usage.prompt_tokens_details.cached_tokens if usage and usage.prompt_tokens_details else 0,
            ),
            model=resolved_model,
            provider="openai",
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
        stream = await self._client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )

        full_content: list[str] = []
        final_usage: Optional[Any] = None
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                full_content.append(delta.content)
                yield delta.content, UsageReport()  # partial — no cost yet
            if chunk.usage:
                final_usage = chunk.usage

        if final_usage:
            report = UsageReport(
                input_tokens=final_usage.prompt_tokens or 0,
                output_tokens=final_usage.completion_tokens or 0,
                cached_input_tokens=final_usage.prompt_tokens_details.cached_tokens if final_usage.prompt_tokens_details else 0,
                cost_usd=compute_cost(
                    resolved_model,
                    final_usage.prompt_tokens or 0,
                    final_usage.completion_tokens or 0,
                    final_usage.prompt_tokens_details.cached_tokens if final_usage.prompt_tokens_details else 0,
                ),
                model=resolved_model,
                provider="openai",
            )
        else:
            report = UsageReport(model=resolved_model, provider="openai")

        # Send final report with empty string to signal end
        yield "", report

    async def embed(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> tuple[list[list[float]], UsageReport]:
        response = await self._client.embeddings.create(model=model, input=texts)
        vectors = [d.embedding for d in response.data]
        usage = response.usage
        report = UsageReport(
            input_tokens=usage.prompt_tokens if usage else 0,
            model=model,
            provider="openai",
        )
        return vectors, report

    async def close(self) -> None:
        await self._client.close()
