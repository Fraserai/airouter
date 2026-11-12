"""Exercise real protocol payloads with a fake HTTP upstream; never spend in pytest."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from router_core.config import load_config
from router_core.gateway.app import create_app
from router_core.ledger.store import SQLiteLedger, execution_cost
from router_core.providers.base import (
    ChatMessage,
    CompletionRequest,
    ProviderError,
    Usage,
)
from router_core.providers.chat_api import ChatAPIAdapter
from router_core.router.leader import RecordedLeader
from router_core.router.runtime import RuntimeRouter, RuntimeRoutingConfig

MODEL = "gpt-4-1-mini@api:default"
USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "prompt_tokens_details": {"cached_tokens": 40},
}


def adapter(handler, key="test-secret"):
    return ChatAPIAdapter(
        "test",
        {MODEL: "upstream-snapshot"},
        base_url="https://upstream.invalid/v1",
        api_key=key,
        transport=httpx.MockTransport(handler),
    )


def response_body(usage=USAGE):
    return {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": usage,
    }


def stream_body(*, done=True, usage=True):
    chunks = [
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    if usage:
        chunks.append({"choices": [], "usage": USAGE})
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + (
        "data: [DONE]\n\n" if done else ""
    )


@pytest.fixture
def live_client(config_dir, monkeypatch, tmp_path):
    import router_core.gateway.app as module

    requests = []

    def upstream(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        if payload["stream"]:
            return httpx.Response(200, text=stream_body())
        return httpx.Response(200, json=response_body())

    original = module.build_adapters

    def build(config):
        registry = original(config)
        for a in registry.adapters():
            if isinstance(a, ChatAPIAdapter):
                # Replace only the transport; the app still constructs its adapters from config.
                a.client = httpx.AsyncClient(
                    base_url="https://upstream.invalid/v1/",
                    headers={"Authorization": "Bearer test-secret"},
                    transport=httpx.MockTransport(upstream),
                )
        return registry

    monkeypatch.setattr(module, "build_adapters", build)
    monkeypatch.setenv("ROUTER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ROUTER_ENV", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    path = tmp_path / "requests.sqlite3"
    monkeypatch.setenv("ROUTER_LEDGER_PATH", str(path))
    with TestClient(create_app()) as client:
        yield client, requests, path


def test_sdk_nonstream_and_stream_record_real_usage_and_discount(live_client):
    client, requests, path = live_client
    sdk = OpenAI(api_key="unused", base_url="http://testserver/v1", http_client=client)
    normal = sdk.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "hi"}],
        max_completion_tokens=16,
        temperature=0,
        extra_body={"router": {"explain": True}},
    )
    assert normal.choices[0].message.content == "hello"
    assert normal.usage.total_tokens == 120
    assert normal.usage.prompt_tokens_details.cached_tokens == 40
    assert normal.model_extra["routing"]["execution_cost_usd"] == pytest.approx(0.000060)
    assert normal.model_extra["routing"]["verification"]["status"] == "unknown"
    chunks = list(
        sdk.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
            stream_options={"include_usage": True},
        )
    )
    assert chunks[-1].choices == []
    assert chunks[-1].usage.total_tokens == 120
    assert requests[0]["model"] == "gpt-4.1-mini-2025-04-14"
    assert requests[0]["max_completion_tokens"] == 16
    assert requests[0]["temperature"] == 0
    assert requests[0]["store"] is False
    assert requests[0]["service_tier"] == "default"
    assert "router" not in requests[0]
    assert requests[1]["stream_options"]["include_usage"] is True
    stats = client.get("/v1/routing/stats").json()
    assert stats["completed"] == 2
    assert stats["known_execution_cost_usd"] == pytest.approx(0.000120)
    assert stats["spend_complete"] is True
    ledger = SQLiteLedger(str(path))
    events = ledger.events(normal.id)
    assert [e["event"] for e in events] == ["started", "completed"]
    assert events[0]["payload"]["request"]["messages"][0]["content"] == "hi"
    assert events[0]["payload"]["model_snapshot"]["provider_model_id"] == requests[0]["model"]
    assert "test-secret" not in json.dumps(events)
    ledger.close()


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": []},
        {"n": 2},
        {"router": {"max_cost_usd": 0.01}},
        {"max_completion_tokens": 0},
        {"messages": []},
    ],
)
def test_unsupported_or_invalid_requests_do_not_call_provider(live_client, extra):
    client, requests, _ = live_client
    result = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            **extra,
        },
    )
    assert result.status_code == 422
    assert requests == []


def test_explicit_unknown_model_is_not_silently_replaced(live_client):
    client, requests, _ = live_client
    result = client.post(
        "/v1/chat/completions",
        json={
            "model": "does-not-exist",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert result.status_code == 404
    assert requests == []


@pytest.mark.parametrize("status,retryable", [(401, False), (429, True), (500, True)])
async def test_errors_hide_upstream_body(status, retryable):
    a = adapter(lambda r: httpx.Response(status, text="echoed test-secret and private prompt"))
    try:
        with pytest.raises(ProviderError) as error:
            await a.complete(CompletionRequest(MODEL, (ChatMessage("user", "hi"),)))
        assert error.value.status == status
        assert error.value.retryable is retryable
        assert "test-secret" not in str(error.value)
        assert "private prompt" not in str(error.value)
    finally:
        await a.aclose()


async def test_missing_key_does_not_touch_network():
    def forbidden(request):
        raise AssertionError("must not contact upstream")

    a = adapter(forbidden, key=None)
    try:
        assert (await a.health())[0] is False
        with pytest.raises(ProviderError, match="not configured"):
            await a.complete(CompletionRequest(MODEL, ()))
    finally:
        await a.aclose()


async def test_timeout_is_a_sanitized_provider_error():
    def timeout(request):
        raise httpx.ReadTimeout("private transport details")

    a = adapter(timeout)
    try:
        with pytest.raises(ProviderError, match="timed out") as error:
            await a.complete(CompletionRequest(MODEL, ()))
        assert error.value.retryable
    finally:
        await a.aclose()


@pytest.mark.parametrize("payload", [{}, {"choices": []}, response_body({"prompt_tokens": -1})])
async def test_malformed_success_is_rejected(payload):
    a = adapter(lambda r: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError):
            await a.complete(CompletionRequest(MODEL, ()))
    finally:
        await a.aclose()


async def test_truncated_stream_is_not_reported_as_success():
    a = adapter(lambda r: httpx.Response(200, text=stream_body(done=False)))
    try:
        with pytest.raises(ProviderError, match="disconnected"):
            _ = [c async for c in a.stream(CompletionRequest(MODEL, (), stream=True))]
    finally:
        await a.aclose()


async def test_missing_usage_is_explicitly_estimated():
    a = adapter(lambda r: httpx.Response(200, json=response_body(None)))
    try:
        result = await a.complete(CompletionRequest(MODEL, ()))
        assert result.usage.estimated
    finally:
        await a.aclose()


def test_missing_usage_and_partial_spend_are_never_zero_cost(config_dir, tmp_path):
    entry = load_config(config_dir, env="live").registry.get(MODEL)
    assert execution_cost(entry, None) is None
    assert execution_cost(entry, Usage(10, 10, estimated=True)) is None
    ledger = SQLiteLedger(str(tmp_path / "audit.sqlite3"))
    ledger.append("a", "started", {})
    ledger.append("a", "failed", {"execution_cost_usd": None})
    ledger.append("b", "started", {})
    assert ledger.stats()["unknown_cost_requests"] == 1
    assert ledger.stats()["unfinished"] == 1
    assert ledger.stats()["spend_complete"] is False
    ledger.close()


def test_ledger_accumulates_known_routing_spend_separately(tmp_path):
    ledger = SQLiteLedger(str(tmp_path / "routing.sqlite3"))
    ledger.append("a", "started", {"routing_cost_usd": 0.01})
    ledger.append("a", "completed", {"routing_cost_usd": 0.01})
    ledger.append("b", "completed", {"routing_cost_usd": None})
    assert ledger.routing_spend_usd() == pytest.approx(0.01)
    ledger.close()


def test_verified_live_prices_do_not_require_inventing_benchmarks(config_dir):
    config = load_config(config_dir, env="live")
    entry = config.registry.get(MODEL)
    assert entry.is_selectable
    assert entry.benchmark.cost_per_task_usd is None
    assert not entry.scores.has_subscores
    assert config.registry.version == load_config(config_dir, env="live").registry.version
    assert MODEL not in load_config(config_dir, env="dev").registry
    assert "dev-stub@stub:default" not in load_config(config_dir, env="production").registry


def test_failed_and_cancelled_requests_are_recorded(client):
    class Failing:
        name = "failing"

        def supports(self, model_id):
            return True

        async def complete(self, request):
            raise ProviderError("provider request failed (HTTP 429)", status=429)

        async def stream(self, request):
            raise asyncio.CancelledError()
            yield  # make this an async iterator

    from router_core.providers.base import AdapterRegistry

    registry = AdapterRegistry()
    registry.register(Failing())
    client.app.state.adapters = registry
    result = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert result.status_code == 429
    client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    stats = client.get("/v1/routing/stats").json()
    assert stats["failed"] == 1
    assert stats["cancelled"] == 1
    assert stats["unfinished"] == 0


def test_runtime_route_uses_recorded_leader_with_explicit_provenance(live_client):
    client, requests, _ = live_client
    config = client.app.state.config
    client.app.state.runtime_router = RuntimeRouter(
        config.registry,
        leader=RecordedLeader('{"model_id":"gpt-4-1-mini@api:default"}'),
        quality_floors={},
        config=RuntimeRoutingConfig(spend_budget_usd=1.0),
    )
    result = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "router": {"runtime": True, "explain": True},
        },
    )
    assert result.status_code == 200
    assert result.json()["model"] == MODEL
    routing = result.json()["routing"]
    assert routing["decision_source"] == "recorded_leader"
    assert routing["frontier_authored"] is False
    assert requests[-1]["model"] == "gpt-4.1-mini-2025-04-14"
