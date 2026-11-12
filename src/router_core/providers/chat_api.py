"""Config-driven adapter for the Chat Completions HTTP protocol."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx

from router_core.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    StreamChunk,
    Usage,
)
from router_core.providers.messages import Message, MessageDelta


def parse_usage(raw: dict | None) -> Usage:
    if not raw:
        return Usage(0, 0, estimated=True)
    try:
        inputs = raw["prompt_tokens"]
        outputs = raw["completion_tokens"]
        details = raw.get("prompt_tokens_details") or {}
        if not isinstance(details, dict):
            raise ValueError
        if "cached_tokens" in raw and "cached_tokens" in details:
            if raw["cached_tokens"] != details["cached_tokens"]:
                raise ValueError
        cached = details.get("cached_tokens", raw.get("cached_tokens", 0))
        written = (raw.get("prompt_tokens_details") or {}).get("cache_write_tokens", 0)
        reasoning = (raw.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        if any(type(n) is not int or n < 0 for n in (inputs, outputs, cached, written, reasoning)):
            raise ValueError
        if cached + written > inputs or reasoning > outputs:
            raise ValueError
        return Usage(
            inputs,
            outputs,
            cached,
            reasoning_output_tokens=reasoning,
            cache_write_input_tokens=written,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ProviderError("provider returned invalid token usage") from exc


class ChatAPIAdapter:
    def __init__(
        self,
        name: str,
        models: dict[str, str],
        *,
        base_url: str,
        api_key: str | None,
        timeout_s: float = 60,
        default_max_tokens: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
        auth_required: bool = True,
        token_limit_parameter: str = "max_completion_tokens",
        request_defaults: dict | None = None,
        model_parameters: dict[str, dict] | None = None,
    ):
        self.name = name
        self.models = models
        self.configured = bool(api_key) or not auth_required
        self.default_max_tokens = default_max_tokens
        if token_limit_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("unsupported token limit parameter")
        self.token_limit_parameter = token_limit_parameter
        self.request_defaults = (
            {"store": False, "service_tier": "default"}
            if request_defaults is None
            else request_defaults
        )
        self.model_parameters = model_parameters or {}
        for defaults in [self.request_defaults, *self.model_parameters.values()]:
            if set(defaults) - {"store", "service_tier", "reasoning_effort", "verbosity"}:
                raise ValueError("unsupported provider default parameter")
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout_s,
            transport=transport,
        )

    def supports(self, model_id: str) -> bool:
        return model_id in self.models

    def _payload(self, request: CompletionRequest) -> dict:
        if not self.configured:
            raise ProviderError("provider API key is not configured", status=503)
        return self.snapshot_request(request)

    def snapshot_request(self, request: CompletionRequest) -> dict:
        """Exact generation payload, without credentials or HTTP headers."""
        if request.model_id not in self.models:
            raise ProviderError("model is not supported by this adapter", status=404)
        payload = {
            **self.request_defaults,
            **self.model_parameters.get(request.model_id, {}),
            **request.extra,
            "model": self.models[request.model_id],
            "messages": [m.to_wire() for m in request.messages],
            self.token_limit_parameter: request.max_tokens or self.default_max_tokens,
            "stream": request.stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.stop:
            payload["stop"] = list(request.stop)
        if request.stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if not response.is_success:
            status = response.status_code
            # Error bodies can contain credentials or echoed prompts. Never relay them.
            raise ProviderError(
                f"provider request failed (HTTP {status})",
                retryable=status == 429 or status >= 500,
                status=status,
            )

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        payload = self._payload(request)
        started = time.perf_counter()
        try:
            response = await self.client.post("chat/completions", json=payload)
            self._check(response)
            raw = response.json()
            choice = raw["choices"][0]
            if len(raw["choices"]) != 1:
                raise ValueError
            message_raw = choice["message"]
            unsupported = set(message_raw) - set(Message.model_fields)
            if any(message_raw[k] for k in unsupported):
                raise ValueError
            message = Message.model_validate(
                {
                    "role": "assistant",
                    **{k: v for k, v in message_raw.items() if k in Message.model_fields},
                }
            )
            if message.role != "assistant":
                raise ValueError
            return CompletionResult(
                model_id=request.model_id,
                content=message.content or "",
                usage=parse_usage(raw.get("usage")),
                finish_reason=choice.get("finish_reason") or "stop",
                latency_ms=(time.perf_counter() - started) * 1000,
                provider_fingerprint=raw.get("system_fingerprint"),
                tool_calls=tuple(t.model_dump() for t in message.tool_calls or []),
                refusal=message.refusal,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("provider connection failed or timed out", retryable=True) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderError("provider returned an invalid completion") from exc

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        payload = self._payload(request)
        try:
            async with self.client.stream("POST", "chat/completions", json=payload) as response:
                self._check(response)
                finished = False
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if not finished:
                            raise ProviderError("provider stream ended without a finish reason")
                        return
                    raw = json.loads(data)
                    if "error" in raw:
                        raise ProviderError("provider stream reported an error")
                    for choice in raw.get("choices", []):
                        if choice.get("index", 0) != 0:
                            raise ValueError
                        delta = MessageDelta.model_validate(choice.get("delta") or {})
                        reason = choice.get("finish_reason")
                        finished = finished or reason is not None
                        yield StreamChunk(
                            delta=delta.content or "",
                            finish_reason=reason,
                            message_delta=delta.model_dump(exclude_none=True),
                        )
                    if raw.get("usage") is not None:
                        yield StreamChunk(delta="", usage=parse_usage(raw["usage"]))
                raise ProviderError(
                    "provider stream disconnected before completion", retryable=True
                )
        except httpx.HTTPError as exc:
            raise ProviderError("provider connection failed or timed out", retryable=True) from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("provider returned an invalid stream") from exc

    async def health(self) -> tuple[bool, str]:
        # Readiness only: health polling must not spend money or require model-list access.
        return self.configured, "credentials configured" if self.configured else "missing API key"

    async def aclose(self) -> None:
        await self.client.aclose()
