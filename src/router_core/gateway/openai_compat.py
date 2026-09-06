"""OpenAI-compatible wire schemas.

Drop-in is the point: an unmodified OpenAI SDK pointed at this base URL must
work. Router-specific controls live in an optional `router` object (or
`x-router-*` headers) so a vanilla client never has to know about them.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from router_core.providers.base import ChatMessage, CompletionRequest, Usage


class WireMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | None = None


class RouterOptions(BaseModel):
    """BRIEF §7 request extensions. All optional."""

    model_config = ConfigDict(extra="forbid")

    quality_floor: str | None = None
    max_cost_usd: float | None = None
    latency_slo_ms: int | None = None
    placement_allow: list[str] | None = None
    pin_model: str | None = None
    explain: bool = False


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "auto"
    messages: list[WireMessage]
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    stop: str | list[str] | None = None
    stream: bool = False
    router: RouterOptions = Field(default_factory=RouterOptions)

    def to_internal(self, model_id: str) -> CompletionRequest:
        stop: tuple[str, ...] = ()
        if isinstance(self.stop, str):
            stop = (self.stop,)
        elif isinstance(self.stop, list):
            stop = tuple(self.stop)
        return CompletionRequest(
            model_id=model_id,
            messages=tuple(
                ChatMessage(role=m.role, content=m.content or "") for m in self.messages
            ),
            max_tokens=self.max_tokens or self.max_completion_tokens,
            temperature=self.temperature,
            stop=stop,
            stream=self.stream,
        )


class WireUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # Non-standard but honest: says the counts did not come from the provider.
    estimated: bool = False

    @classmethod
    def from_usage(cls, usage: Usage) -> WireUsage:
        return cls(
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            estimated=usage.estimated,
        )


class WireChoice(BaseModel):
    index: int = 0
    message: WireMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:24]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[WireChoice]
    usage: WireUsage
    # Present only when router.explain is true.
    routing: dict[str, Any] | None = None


def stream_chunk(completion_id: str, model: str, delta: str, finish_reason: str | None) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": ({"content": delta} if delta else {}),
                "finish_reason": finish_reason,
            }
        ],
    }
