"""Provider adapter protocol and implementations.

Every LLM provider exposes a common interface so the AI router never
imports a vendor SDK directly.

The pattern is::

    adapter = get_provider(model_profile_id, db)
    result = await adapter.chat(messages, tools)

Cost and token usage are reported back via ``UsageReport``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, AsyncIterator, Optional

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UsageReport:
    """Token and cost breakdown for a single LLM call.

    ``cost_usd`` is ALWAYS in USD — every provider cost card is priced per
    1K tokens in USD (see compute_cost / provider _COST_CARDS). Tracked
    explicitly via UsageEvent.currency = 'USD' in nexus_ai.usage_events.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    model: str = ""
    provider: str = ""


class ProviderAdapter(ABC):
    """Interface every provider adapter must implement."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, UsageReport]:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[tuple[str, UsageReport]]:
        ...  # typed as async generator — concrete impl yields (text, report) tuples

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, list[dict[str, Any]], UsageReport]:
        """Chat with function-calling support.

        2026-09-09: real tool calling for write-draft flow (Terrence: AI 一直
        文字扮 draft — model 冇真 tools schema 就唔會 call tool)。

        Default impl: providers without function calling just fall back to
        plain chat and return no tool calls. Override in providers that
        support tools (deepseek / openai-compatible).
        """
        text, report = await self.chat(
            messages=messages, model=model,
            temperature=temperature, max_tokens=max_tokens,
            tools=tools,
        )
        return text, [], report

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str = "",
    ) -> tuple[list[list[float]], UsageReport]:
        ...

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Cost tables  (per-1K-token, in USD)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostCard:
    input_per_1k: Decimal
    output_per_1k: Decimal
    cached_input_per_1k: Decimal = Decimal("0")


_MODEL_COSTS: dict[str, CostCard] = {
    # OpenAI
    "gpt-4o": CostCard(Decimal("0.0025"), Decimal("0.010")),
    "gpt-4o-mini": CostCard(Decimal("0.00015"), Decimal("0.0006")),
    "o3": CostCard(Decimal("0.010"), Decimal("0.040"), Decimal("0.0025")),
    "o4-mini": CostCard(Decimal("0.0011"), Decimal("0.0044")),
    "gpt-4.1": CostCard(Decimal("0.002"), Decimal("0.008")),
    "gpt-4.1-mini": CostCard(Decimal("0.0004"), Decimal("0.0016")),
    "gpt-4.1-nano": CostCard(Decimal("0.0001"), Decimal("0.0004")),
    # Anthropic
    "claude-sonnet-4": CostCard(Decimal("0.003"), Decimal("0.015")),
    "claude-sonnet-4-20250514": CostCard(Decimal("0.003"), Decimal("0.015"), Decimal("0.0003")),
    "claude-haiku-3.5": CostCard(Decimal("0.0008"), Decimal("0.004")),
    "claude-opus-4": CostCard(Decimal("0.015"), Decimal("0.075")),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int, cached_input: int = 0) -> Decimal:
    """Compute USD cost from token counts, rounded to 6 decimal places."""
    card = _MODEL_COSTS.get(model)
    if card is None:
        return Decimal("0")

    total = (
        (input_tokens - cached_input) * card.input_per_1k
        + cached_input * card.cached_input_per_1k
        + output_tokens * card.output_per_1k
    ) / Decimal("1000")
    return total.quantize(Decimal("0.000001"))


# Registered adapter builders — populated by subclass registration / config
_ADAPTER_REGISTRY: dict[str, type[ProviderAdapter]] = {}


def register_provider(name: str) -> Any:
    """Decorator that registers a provider adapter class."""

    def _wrap(cls: type[ProviderAdapter]) -> type[ProviderAdapter]:
        _ADAPTER_REGISTRY[name] = cls
        return cls

    return _wrap


def get_provider(provider: str = "openai", **kwargs: Any) -> ProviderAdapter:
    """Factory: instantiate the right adapter by name.

    Parameters
    ----------
    provider
        One of ``"openai"``, ``"anthropic"``.
    """
    cls = _ADAPTER_REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown provider '{provider}'. Registered: {list(_ADAPTER_REGISTRY)}")
    return cls(**kwargs)
