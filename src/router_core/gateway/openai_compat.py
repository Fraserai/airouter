"""OpenAI-compatible wire schemas.

Drop-in is the point: an unmodified OpenAI SDK pointed at this base URL must
work. Router-specific controls live in an optional `router` object (or
`x-router-*` headers) so a vanilla client never has to know about them.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from router_core.providers.base import ChatMessage, CompletionRequest, Usage
from router_core.providers.messages import (
    FunctionTool,
    Message,
    NamedToolChoice,
    ResponseFormat,
)


class WireMessage(Message):
    pass


class RouterOptions(BaseModel):
    """Model Router controls. All optional; automatic routing is the default."""

    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    placement_allow: list[Literal["local", "cloud_open", "closed_frontier"]] | None = None
    pin_model: str | None = None
    explain: bool = False
    # False selects the development baseline only; live auto requires a leader.
    runtime: bool | None = None
    task_class: str | None = Field(default=None, min_length=1, max_length=80)


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    # Unsupported features must not be silently discarded on paid requests.
    model_config = ConfigDict(extra="forbid")

    model: str = "auto"
    messages: list[WireMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    stop: str | list[str] | None = None
    stream: bool = False
    stream_options: StreamOptions | None = None
    tools: list[FunctionTool] | None = Field(default=None, min_length=1, max_length=128)
    tool_choice: Literal["none", "auto", "required"] | NamedToolChoice | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat | None = None
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = None
    router: RouterOptions = Field(default_factory=RouterOptions)

    @model_validator(mode="after")
    def validate_tools(self):
        names = [tool.function.name for tool in self.tools or []]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        if self.tool_choice not in (None, "none") and not names:
            raise ValueError("tool_choice requires tools")
        if isinstance(self.tool_choice, NamedToolChoice):
            if self.tool_choice.function.name not in names:
                raise ValueError("selected tool is not in tools")
        pending: set[str] = set()
        seen: set[str] = set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("tool result must match a pending assistant tool call")
                pending.remove(message.tool_call_id)
            else:
                if pending:
                    raise ValueError("every tool call needs a result before the next message")
                for call in message.tool_calls or []:
                    if call.id in seen:
                        raise ValueError("tool call IDs must be unique")
                    seen.add(call.id)
                    pending.add(call.id)
        if pending:
            raise ValueError("missing tool results")
        return self

    def to_internal(self, model_id: str) -> CompletionRequest:
        stop: tuple[str, ...] = ()
        if isinstance(self.stop, str):
            stop = (self.stop,)
        elif isinstance(self.stop, list):
            stop = tuple(self.stop)
        return CompletionRequest(
            model_id=model_id,
            messages=tuple(
                ChatMessage(
                    role=m.role,
                    content=m.content,
                    name=m.name,
                    tool_calls=tuple(t.model_dump() for t in m.tool_calls or []),
                    tool_call_id=m.tool_call_id,
                    refusal=m.refusal,
                )
                for m in self.messages
            ),
            max_tokens=self.max_completion_tokens or self.max_tokens,
            temperature=self.temperature,
            stop=stop,
            stream=self.stream,
            extra=self.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                include={
                    "tools",
                    "tool_choice",
                    "parallel_tool_calls",
                    "response_format",
                    "top_p",
                    "frequency_penalty",
                    "presence_penalty",
                    "seed",
                },
            ),
        )


class WireUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # Non-standard but honest: says the counts did not come from the provider.
    estimated: bool = False
    prompt_tokens_details: dict[str, int] = Field(default_factory=dict)
    completion_tokens_details: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_usage(cls, usage: Usage) -> WireUsage:
        return cls(
            prompt_tokens=usage.input_tokens,
            completion_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            estimated=usage.estimated,
            prompt_tokens_details={
                "cached_tokens": usage.cached_input_tokens,
                "cache_write_tokens": usage.cache_write_input_tokens,
            },
            completion_tokens_details={"reasoning_tokens": usage.reasoning_output_tokens},
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


def stream_chunk(
    completion_id: str,
    model: str,
    delta: str,
    finish_reason: str | None,
    *,
    message_delta: dict | None = None,
    created: int | None = None,
) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created if created is not None else int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": message_delta
                if message_delta is not None
                else ({"content": delta} if delta else {}),
                "finish_reason": finish_reason,
            }
        ],
    }
