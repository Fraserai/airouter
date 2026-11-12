"""SDK-level tool conversations, streamed arguments, and structured outputs."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from router_core.gateway.app import create_app
from router_core.ledger.replay import replay_request
from router_core.ledger.store import SQLiteLedger
from router_core.providers.base import AdapterRegistry, CompletionRequest
from router_core.providers.chat_api import ChatAPIAdapter

MODEL = "gpt-4-1-mini@api:default"
TOOL = {
    "type": "function",
    "function": {
        "name": "lookup",
        "description": "Look up a public item",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}
CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "lookup", "arguments": '{"id":"42"}'},
}
FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    },
}
USAGE = {"prompt_tokens": 20, "completion_tokens": 10}


@pytest.fixture
def protocol_client(monkeypatch, config_dir, tmp_path):
    import router_core.gateway.app as module

    captured = []

    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        if body["stream"]:
            deltas = [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {"index": 0, **CALL, "function": {"name": "lookup", "arguments": ""}}
                    ],
                },
                {"tool_calls": [{"index": 0, "function": {"arguments": '{"id":'}}]},
                {"tool_calls": [{"index": 0, "function": {"arguments": '"42"}'}}]},
            ]
            events = [
                {"choices": [{"index": 0, "delta": d, "finish_reason": None}]} for d in deltas
            ]
            events.extend(
                [
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                    {"choices": [], "usage": USAGE},
                ]
            )
            return httpx.Response(
                200, text="".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            )
        if body["messages"][-1]["role"] == "tool":
            message = {"role": "assistant", "content": "Found item 42."}
            reason = "stop"
        elif body.get("tools"):
            message = {"role": "assistant", "content": None, "tool_calls": [CALL]}
            reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": '{"answer":"42"}'}
            reason = "stop"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message, "finish_reason": reason}],
                "usage": USAGE,
            },
        )

    def build(config):
        registry = AdapterRegistry()
        registry.register(
            ChatAPIAdapter(
                "mock",
                {MODEL: "snapshot"},
                base_url="https://mock.invalid/v1",
                api_key="hidden",
                transport=httpx.MockTransport(handler),
            )
        )
        return registry

    monkeypatch.setattr(module, "build_adapters", build)
    monkeypatch.setenv("ROUTER_ENV", "live")
    monkeypatch.setenv("ROUTER_CONFIG_DIR", str(config_dir))
    path = tmp_path / "requests.sqlite3"
    monkeypatch.setenv("ROUTER_LEDGER_PATH", str(path))
    with TestClient(create_app()) as client:
        yield client, captured, path


def test_sdk_tool_call_and_tool_result_are_preserved(protocol_client):
    client, captured, _ = protocol_client
    sdk = OpenAI(api_key="unused", base_url="http://testserver/v1", http_client=client)
    messages = [{"role": "user", "content": "Look up 42."}]
    response = sdk.chat.completions.create(model=MODEL, messages=messages, tools=[TOOL])
    assert response.choices[0].finish_reason == "tool_calls"
    message = response.choices[0].message
    assert message.content is None
    assert message.tool_calls[0].function.arguments == '{"id":"42"}'
    messages += [message, {"role": "tool", "tool_call_id": "call_1", "content": "item 42"}]
    final = sdk.chat.completions.create(model=MODEL, messages=messages, tools=[TOOL])
    assert final.choices[0].message.content == "Found item 42."
    assert captured[-1]["messages"][1]["tool_calls"] == [CALL]
    assert captured[-1]["messages"][2]["tool_call_id"] == "call_1"


def test_sdk_reassembles_streamed_arguments(protocol_client):
    client, _, _ = protocol_client
    sdk = OpenAI(api_key="unused", base_url="http://testserver/v1", http_client=client)
    chunks = list(
        sdk.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Look up 42."}],
            tools=[TOOL],
            stream=True,
            stream_options={"include_usage": True},
        )
    )
    arguments = "".join(
        t.function.arguments or ""
        for chunk in chunks
        for choice in chunk.choices
        for t in choice.delta.tool_calls or []
    )
    assert json.loads(arguments) == {"id": "42"}
    assert chunks[0].choices[0].delta.tool_calls[0].id == "call_1"
    assert chunks[-2].choices[0].finish_reason == "tool_calls"
    assert chunks[-1].choices == [] and chunks[-1].usage.total_tokens == 30
    assert len({chunk.created for chunk in chunks}) == 1


def test_schema_and_replay_use_the_exact_original_request(protocol_client):
    client, captured, path = protocol_client
    result = client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "Return 42"}],
            "response_format": FORMAT,
            "max_completion_tokens": 30,
        },
    )
    assert result.status_code == 200
    assert captured[0]["response_format"] == FORMAT
    ledger = SQLiteLedger(str(path))
    replay = replay_request(ledger, result.json()["id"])
    assert replay["decision_matches"] and replay["request_matches"]
    assert replay["provider_request"] == captured[0]
    assert replay["executed"] is False
    assert "hidden" not in json.dumps(replay)
    assert len(captured) == 1
    ledger.close()


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "tool", "tool_call_id": "unknown", "content": "result"}],
        [{"role": "assistant", "tool_calls": [CALL]}],
        [{"role": "assistant", "tool_calls": [CALL]}, {"role": "user", "content": "next"}],
        [{"role": "user", "content": "x", "tool_calls": [CALL]}],
    ],
)
def test_invalid_tool_history_never_reaches_upstream(protocol_client, messages):
    client, captured, _ = protocol_client
    result = client.post("/v1/chat/completions", json={"model": MODEL, "messages": messages})
    assert result.status_code == 422
    assert captured == []


async def test_refusal_keeps_its_own_field():
    adapter = ChatAPIAdapter(
        "mock",
        {"model": "snapshot"},
        base_url="https://mock.invalid/v1",
        api_key="hidden",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "refusal": "Cannot assist.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": USAGE,
                },
            )
        ),
    )
    try:
        result = await adapter.complete(CompletionRequest("model", ()))
        assert result.content == ""
        assert result.refusal == "Cannot assist."
    finally:
        await adapter.aclose()


async def test_local_compatible_endpoint_needs_no_fake_key_and_uses_its_token_parameter():
    captured = []

    def handler(request):
        assert "authorization" not in request.headers
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "local"}, "finish_reason": "stop"}],
                "usage": USAGE,
            },
        )

    adapter = ChatAPIAdapter(
        "local",
        {"model": "local-model"},
        base_url="http://127.0.0.1:1234/v1",
        api_key=None,
        auth_required=False,
        token_limit_parameter="max_tokens",
        request_defaults={},
        transport=httpx.MockTransport(handler),
    )
    try:
        assert (
            await adapter.complete(CompletionRequest("model", (), max_tokens=50))
        ).content == "local"
        assert captured[0]["max_tokens"] == 50
        assert "service_tier" not in captured[0] and "store" not in captured[0]
    finally:
        await adapter.aclose()
