"""Deterministic stub adapter.

Exists so M0/M1 can prove the full path end to end without credentials and
without inventing a single price. Its cost really is zero, so putting it in the
registry as `verified` is honest rather than a fudge.

Dev only. `load_dev_registry_overlay` is gated on ROUTER_ENV and the gateway
refuses to serve this adapter when ROUTER_ENV=production.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator

from router_core.providers.base import (
    CompletionRequest,
    CompletionResult,
    StreamChunk,
    Usage,
)

_CHARS_PER_TOKEN = 4  # crude, and flagged as estimated in Usage


def _count_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class StubAdapter:
    """Echoes a deterministic transform of the input. Same input -> same output."""

    name = "stub"

    def __init__(self, model_ids: tuple[str, ...] = ("dev-stub@stub",), delay_ms: float = 5.0):
        self._model_ids = set(model_ids)
        self._delay_ms = delay_ms

    def supports(self, model_id: str) -> bool:
        return model_id in self._model_ids

    def _render(self, request: CompletionRequest) -> str:
        joined = "\n".join(f"{m.role}: {m.content}" for m in request.messages)
        digest = hashlib.sha256(joined.encode()).hexdigest()[:12]
        last = request.messages[-1].content if request.messages else ""
        return f"[stub:{request.model_id}#{digest}] {last[:400]}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        await asyncio.sleep(self._delay_ms / 1000.0)
        content = self._render(request)
        prompt = "\n".join(m.content for m in request.messages)
        return CompletionResult(
            model_id=request.model_id,
            content=content,
            usage=Usage(
                input_tokens=_count_tokens(prompt),
                output_tokens=_count_tokens(content),
                estimated=True,  # the stub cannot report real usage; say so
            ),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            ttft_ms=self._delay_ms,
            provider_fingerprint="stub-v1",
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        result = await self.complete(request)
        words = result.content.split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(self._delay_ms / 1000.0 / max(len(words), 1))
            yield StreamChunk(delta=word + (" " if i < len(words) - 1 else ""))
        yield StreamChunk(delta="", finish_reason="stop", usage=result.usage)

    async def health(self) -> tuple[bool, str]:
        return True, "stub adapter always healthy"
