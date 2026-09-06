"""The single provider interface.

Local, cloud-open and closed-frontier adapters are indistinguishable from the
router's point of view (BRIEF §8, non-negotiables). Anything placement-specific
belongs in the registry or the costing module, never here and never in the
router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    """Normalised request handed to an adapter.

    `model_id` is a REGISTRY id, not a provider model string. The adapter is
    responsible for translating it; the router never learns provider naming.
    """

    model_id: str
    messages: tuple[ChatMessage, ...]
    max_tokens: int | None = None
    temperature: float | None = None
    stop: tuple[str, ...] = ()
    stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Usage:
    """Token counts as REPORTED BY THE PROVIDER. Never estimated.

    `estimated` exists so a provider that cannot report usage is visibly
    untrustworthy in the ledger rather than quietly polluting the cost figures.
    """

    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CompletionResult:
    model_id: str
    content: str
    usage: Usage
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    provider_fingerprint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamChunk:
    delta: str
    finish_reason: str | None = None
    usage: Usage | None = None


class ProviderError(RuntimeError):
    """Adapter-level failure. Carries whether a retry could plausibly help."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@runtime_checkable
class ProviderAdapter(Protocol):
    """Every adapter implements exactly this."""

    name: str

    def supports(self, model_id: str) -> bool: ...

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]: ...

    async def health(self) -> tuple[bool, str]: ...


class AdapterRegistry:
    """Maps a registry model id to the adapter that can serve it."""

    def __init__(self) -> None:
        self._adapters: list[ProviderAdapter] = []

    def register(self, adapter: ProviderAdapter) -> None:
        self._adapters.append(adapter)

    def adapters(self) -> list[ProviderAdapter]:
        return list(self._adapters)

    def for_model(self, model_id: str) -> ProviderAdapter:
        for a in self._adapters:
            if a.supports(model_id):
                return a
        raise ProviderError(f"no adapter serves model id: {model_id}")

    def __len__(self) -> int:
        return len(self._adapters)
