"""M0 gateway: the path works end to end, and refuses to serve unverified models."""

from __future__ import annotations

import json


def test_health_reports_registry_and_routing_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["adapters"]["openrouter"]["optional"] is True
    assert body["product"] == "Model Router"
    assert body["runtime_routing"]["enabled"] is True
    assert body["registry"]["total"] == 24  # 23 catalog entries + 1 dev stub
    assert body["intelligence_model"]  # configured, not hardcoded


def test_branded_landing_page_uses_supplied_gradient_asset(client):
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "More intelligence." in page.text
    assert "Less cost." in page.text
    assert "Send a request once." in page.text
    assert "One API for your model stack." in page.text
    assert "/brand/model-router-gradient-logo.png" in page.text
    assert "/brand/model-router-logo.png" in page.text
    assert "/docs#/default/chat_completions_v1_chat_completions_post" in page.text


def test_branded_logo_asset_is_served(client):
    asset = client.get("/brand/model-router-logo.png")
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "image/png"
    assert asset.content.startswith(b"\x89PNG")


def test_models_endpoint_explains_why_entries_are_blocked(client):
    body = client.get("/v1/models").json()
    assert body["registry_version"].startswith("reg_")
    by_id = {m["id"]: m for m in body["data"]}
    frontier = by_id["fable-5-1@frontier:max"]
    assert frontier["selectable"] is False
    assert "unverified" in frontier["blocked_by"]
    assert frontier["has_subscores"] is False
    assert by_id["dev-stub@stub:default"]["selectable"] is True


def test_only_the_stub_is_selectable_on_a_fresh_checkout(client):
    body = client.get("/v1/models").json()
    selectable = [m["id"] for m in body["data"] if m["selectable"]]
    assert selectable == ["dev-stub@stub:default"]


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
            "router": {"pin_model": "fable-5-1@frontier:max"},
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
    assert plan["selection_mode"] == "intelligent"
    assert plan["frontier_authored"] is False
    assert plan["registry_version"].startswith("reg_")
    assert plan["provisional"] is True


def test_explain_is_absent_unless_requested(client):
    body = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
    ).json()
    assert body.get("routing") is None


def test_dashboard_is_read_only_and_exposes_current_pool(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Model Router" in response.text
    assert "dev-stub@stub:default" in response.text
    assert "router-data" in response.text
    assert "OPENAI_API_KEY" not in response.text


def test_routing_simulation_is_read_only_and_reports_provenance(client):
    response = client.post(
        "/v1/routing/simulate",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "router": {"runtime": True},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["simulated"] is True
    assert body["executes"] is False
    assert body["selection_mode"] == "candidate_preview"
    assert body["routing"]["frontier_authored"] is False
    assert body["routing"]["decision_source"] == "deterministic_fallback"
    assert body["projected_execution_cost_usd"] == 0.0
    assert client.get("/v1/routing/stats").json()["requests"] == 0


def test_autonomous_job_routes_are_removed(client):
    assert client.post("/v1/jobs", json={}).status_code == 404
    assert client.get("/v1/jobs/old-job").status_code == 404
    assert client.post("/v1/jobs/old-job/cancel").status_code == 404
    assert not any("/jobs" in path for path in client.get("/openapi.json").json()["paths"])


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
