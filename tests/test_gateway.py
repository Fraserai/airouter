"""M0 gateway: the path works end to end, and refuses to serve unverified models."""

from __future__ import annotations

import json


def test_health_reports_registry_and_milestone(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["milestone"] == "M0"
    assert body["registry"]["total"] == 23  # 22 seed + 1 dev stub
    assert body["intelligence_model"]  # configured, not hardcoded


def test_models_endpoint_explains_why_entries_are_blocked(client):
    body = client.get("/v1/models").json()
    assert body["registry_version"].startswith("reg_")
    by_id = {m["id"]: m for m in body["data"]}
    frontier = by_id["fable-5-1@frontier"]
    assert frontier["selectable"] is False
    assert "unverified" in frontier["blocked_by"]
    assert frontier["has_subscores"] is False
    assert by_id["dev-stub@stub"]["selectable"] is True


def test_only_the_stub_is_selectable_on_a_fresh_checkout(client):
    body = client.get("/v1/models").json()
    selectable = [m["id"] for m in body["data"] if m["selectable"]]
    assert selectable == ["dev-stub@stub"]


def test_chat_completion_round_trip(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hello router"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"].startswith("[stub:")
    assert body["usage"]["total_tokens"] > 0


def test_usage_is_flagged_when_estimated_rather_than_provider_reported(client):
    body = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    ).json()
    assert body["usage"]["estimated"] is True, "a provider that cannot report usage must say so"


def test_serving_an_unverified_model_is_refused(client):
    """Never silently serve from an unverified entry."""
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "router": {"pin_model": "fable-5-1@frontier"},
        },
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "model_not_selectable"
    assert "unverified" in detail["blocked_by"]


def test_unknown_model_is_404(client):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "router": {"pin_model": "does-not-exist@nowhere"},
        },
    )
    assert resp.status_code == 404


def test_explain_returns_a_plan_marked_provisional(client):
    body = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "router": {"explain": True},
        },
    ).json()
    plan = body["routing"]
    assert plan["milestone"] == "M0"
    assert plan["deciding_tier"] is None
    assert plan["registry_version"].startswith("reg_")
    assert plan["provisional"] is True


def test_explain_is_absent_unless_requested(client):
    body = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    ).json()
    assert body.get("routing") is None


def test_streaming_emits_sse_chunks_and_terminates(client):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "stream me"}],
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        lines = [ln for ln in resp.iter_lines() if ln.strip()]

    assert lines[-1] == "data: [DONE]"
    payloads = [json.loads(ln.removeprefix("data: ")) for ln in lines[:-1]]
    assert all(p["object"] == "chat.completion.chunk" for p in payloads)
    text = "".join(p["choices"][0]["delta"].get("content", "") for p in payloads)
    assert "stub:" in text
