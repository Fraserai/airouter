"""Product contract: frontier decision, shared execution pool, honest economics."""

import json
import shutil
from datetime import date

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from router_core.config import load_config
from router_core.gateway.app import create_app
from router_core.providers.base import AdapterRegistry
from router_core.providers.chat_api import ChatAPIAdapter
from router_core.registry.schema import ModelEntry, Scores

BRAIN = "gpt-6-astra@frontier:max"
OPEN = "test-open@cloud:default"
BASELINE = "gpt-4-1-mini@api:default"


@pytest.fixture
def routed_client(config_dir, monkeypatch, tmp_path):
    """Real gateway and provider adapter, isolated HTTP transport; no paid calls."""
    import router_core.gateway.app as module

    copied = tmp_path / "config"
    shutil.copytree(config_dir, copied)
    path = copied / "models.live.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["models"].append(
        {
            "id": OPEN,
            "display_name": "Test open deployment",
            "family": "glm-5-3-flash",
            "access": "open",
            "placement": "cloud_open",
            "lifecycle": "executor",
            "verified": True,
            "provider": "test",
            "provider_model_id": "test-open",
            "context_window": 32000,
            "api_features": ["json_schema"],
            "pricing": {"input_usd_per_mtok": 0.1, "output_usd_per_mtok": 0.2},
        }
    )
    path.write_text(yaml.safe_dump(doc))
    captured = []
    control = {"select": OPEN, "failure": None, "configured": True}

    def upstream(request):
        payload = json.loads(request.content)
        captured.append(payload)
        fmt = payload.get("response_format", {}).get("json_schema", {})
        consultation = fmt.get("name") == "routing_decision"
        if consultation:
            if control["failure"] == "outage":
                return httpx.Response(503)
            if control["failure"] == "invalid":
                content = json.dumps({"model_id": "not-offered"})
            else:
                content = json.dumps({"model_id": control["select"], "reason": "Task fit"})
        else:
            content = "The requested answer."
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    def build(config):
        adapters = AdapterRegistry()
        entries = [entry for entry in config.registry.all() if entry.is_selectable]
        adapter = ChatAPIAdapter(
            "test",
            {entry.id: entry.id for entry in entries},
            base_url="https://router-test.invalid/v1",
            api_key="test-only",
            transport=httpx.MockTransport(upstream),
        )
        adapter.configured = control["configured"]
        adapters.register(adapter)
        return adapters

    monkeypatch.setattr(module, "build_adapters", build)
    monkeypatch.setenv("ROUTER_CONFIG_DIR", str(copied))
    monkeypatch.setenv("ROUTER_ENV", "live")
    monkeypatch.setenv("ROUTER_LEDGER_PATH", ":memory:")
    with TestClient(create_app()) as client:
        yield client, captured, control


def test_catalog_preserves_supplied_snapshot_and_is_separate_from_deployments(client):
    body = client.get("/v1/catalog").json()
    assert len(body["data"]) == 23
    assert body["source"]["snapshot_date"] == "2026-09-08"
    by_name = {row["name"]: row for row in body["data"]}
    expected = {
        "GPT-6 Astra": (53, 3.26),
        "Claude Fable 5.1": (53, 7.63),
        "Claude Opus 5": (51, 5.86),
        "Claude Fable 5": (50, 8.75),
        "Muse Spark 1.3": (48, 1.60),
        "GPT-5.6 Sol": (47, 1.99),
        "GLM-5.3": (45, 2.01),
        "Grok 4.6": (44, 1.86),
        "Kimi K3": (44, 2.00),
        "GPT-5.6 Terra": (42, 1.40),
        "GLM-5.3-Flash": (42, 0.25),
        "Gemini 3.8 Flash": (41, 1.24),
        "Qwen3.8 247B A95B": (40, 2.16),
        "GPT-5.6 Luna": (38, 0.18),
        "DeepSeek V4 Pro 0813": (36, 0.67),
        "Qwen3.8 27B": (34, 0.82),
        "MiniMax-M3": (30, 0.51),
        "Inkling": (26, 0.61),
        "Nemotron 3 Ultra": (23, 0.58),
        "Gemini 3.5 Flash-Lite": (23, 0.12),
        "Muse Glimmer": (18, 0.06),
        "Mistral Medium 3.5": (15, 0.44),
        "gpt-oss-120b": (12, 0.11),
    }
    assert set(by_name) == set(expected)
    for name, (score, cost) in expected.items():
        assert by_name[name]["intelligence_index"] == score
        assert by_name[name]["benchmark_cost_per_task_usd"] == cost
    assert by_name["GPT-6 Astra"]["rank"] == by_name["Claude Fable 5.1"]["rank"] == 1
    assert body["data"][0]["id"] == BRAIN
    assert all(not row["access_verified"] for row in body["data"])
    assert "dev-stub@stub:default" not in {row["id"] for row in body["data"]}


@pytest.mark.parametrize("selected", [OPEN, BRAIN])
def test_default_auto_consults_brain_then_executes_selected_model(routed_client, selected):
    client, calls, control = routed_client
    control["select"] = selected
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "Solve this task"}],
            "router": {"explain": True},
        },
    )
    assert response.status_code == 200, response.text
    assert [call["model"] for call in calls] == [BRAIN, selected]
    assert calls[1]["max_completion_tokens"] == 1024
    menu = json.loads(calls[0]["messages"][1]["content"])["candidates"]
    assert BRAIN in {item["model"] for item in menu}
    open_offer = next(item for item in menu if item["model"] == OPEN)
    assert open_offer["market_reference"]["intelligence_index"] == 42
    assert open_offer["market_reference"]["configuration_verified"] is False
    result = response.json()
    assert result["routing"]["frontier_authored"] is True
    assert result["routing"]["leader_model"] == BRAIN
    stats = client.get("/v1/routing/stats").json()
    assert stats["requests"] == stats["completed"] == 1
    assert stats["known_routing_cost_usd"] == pytest.approx(0.002)
    assert stats["total_cost_usd"] == pytest.approx(result["routing"]["total_cost_usd"])
    assert stats["savings_usd"] is None
    assert stats["execution_mix"]["requests"] == 1


@pytest.mark.parametrize("failure,known", [("invalid", True), ("outage", False)])
def test_failed_consult_never_executes_and_preserves_cost(routed_client, failure, known):
    client, calls, control = routed_client
    control["failure"] = failure
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "A hard task"}],
        },
    )
    assert response.status_code == 503
    assert len(calls) == 1
    assert response.headers["x-request-id"]
    stats = client.get("/v1/routing/stats").json()
    assert stats["requests"] == stats["failed"] == 1
    assert stats["known_execution_cost_usd"] == 0
    assert stats["routing_spend_complete"] is known
    assert stats["execution_mix"]["requests"] == 0
    if known:
        assert stats["total_cost_usd"] == pytest.approx(0.002)
    else:
        assert stats["total_cost_usd"] is None


def test_request_budget_reserves_routing_cost_before_any_call(routed_client):
    client, calls, _ = routed_client
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
            "router": {"max_cost_usd": 0.001},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "request_cost_limit"
    assert not calls


def test_simulation_never_consults_and_does_not_predict_brain_choice(routed_client):
    client, calls, _ = routed_client
    response = client.post(
        "/v1/routing/simulate",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["predicts_live_selection"] is False
    assert response.json()["routing"]["frontier_authored"] is False
    assert not calls
    assert client.get("/v1/routing/stats").json()["requests"] == 0


@pytest.mark.parametrize("endpoint", ["/v1/chat/completions", "/v1/routing/simulate"])
def test_explicit_model_obeys_constraints(routed_client, endpoint):
    client, calls, _ = routed_client
    response = client.post(
        endpoint,
        json={
            "model": BASELINE,
            "messages": [{"role": "user", "content": "Hi"}],
            "router": {"placement_allow": ["local"]},
        },
    )
    assert response.status_code == 422
    assert "placement_not_allowed" in response.json()["detail"]["blocked_by"]
    assert not calls


def test_auto_cannot_silently_revert_to_fixed_live_model(routed_client):
    client, calls, _ = routed_client
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Hi"}],
            "router": {"runtime": False},
        },
    )
    assert response.status_code == 422
    assert not calls


def test_promoting_new_frontier_keeps_previous_brain_in_pool(config_dir):
    from dataclasses import replace

    config = load_config(config_dir, env="live")
    assert config.intelligence_model == BRAIN
    future = ModelEntry(
        id="future-frontier",
        display_name="Future frontier",
        scores=Scores(composite=54, measured_at=date(2026, 9, 9)),
    )
    upgraded = replace(config, catalog=config.catalog.with_entry(future))
    assert upgraded.intelligence_model == "future-frontier"
    assert upgraded.registry.get(BRAIN).is_selectable
    assert not future.is_selectable  # ranking alone does not certify API access
