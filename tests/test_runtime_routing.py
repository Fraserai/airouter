"""Runtime routing contract and failure-path tests."""

import json
from dataclasses import asdict

import pytest

from router_core.gateway.openai_compat import ChatCompletionRequest
from router_core.ledger.replay import replay_request
from router_core.ledger.store import SQLiteLedger
from router_core.providers.base import ChatMessage
from router_core.registry.store import Registry
from router_core.router.candidates import RequestProfile
from router_core.router.digest import DigestLimits
from router_core.router.leader import LeaderUnavailable, RecordedLeader
from router_core.router.protocol import DecisionSource, FallbackReason, PlanRejection
from router_core.router.runtime import RuntimeRouter, RuntimeRoutingConfig


def _router(config_dir, leader, *, budget=1.0):
    from router_core.config import load_config

    source = load_config(config_dir, env="live").registry.get("gpt-4-1-mini@api:default")
    other = source.model_copy(
        deep=True,
        update={
            "id": "candidate-cheap@api:default",
            "provider_model_id": "candidate-cheap",
            "pricing": source.pricing.model_copy(
                update={"input_usd_per_mtok": 0.01, "output_usd_per_mtok": 0.01}
            ),
            "cost": source.cost.model_copy(
                update={
                    "marginal_input_usd_per_mtok": 0.01,
                    "marginal_output_usd_per_mtok": 0.01,
                    "allocated_input_usd_per_mtok": 0.01,
                    "allocated_output_usd_per_mtok": 0.01,
                }
            ),
        },
    )
    registry = Registry([source, other])
    return RuntimeRouter(
        registry,
        leader=leader,
        quality_floors={},
        config=RuntimeRoutingConfig(
            digest_limits=DigestLimits(max_tokens=80, head_chars=120, tail_chars=120),
            spend_budget_usd=budget,
        ),
    )


def _profile():
    return RequestProfile(input_tokens=20, max_output_tokens=20)


@pytest.mark.anyio
async def test_recorded_leader_selects_only_offered_candidate(config_dir):
    leader = RecordedLeader(
        lambda digest, candidates: json.dumps({"model_id": candidates[0].model_id}),
    )
    decision = await _router(config_dir, leader).route([ChatMessage("user", "hello")], _profile())
    assert decision.source == DecisionSource.RECORDED_LEADER
    assert not decision.frontier_authored
    assert decision.model_id in decision.candidates
    assert decision.digest_bounded
    assert decision.routing_cost_usd == 0.0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("raw", "rejection"),
    [
        ("not json", PlanRejection.MALFORMED_JSON),
        (json.dumps({"model_id": "never-offered"}), PlanRejection.MODEL_NOT_OFFERED),
    ],
)
async def test_bad_leader_plan_falls_back_with_reason(config_dir, raw, rejection):
    decision = await _router(config_dir, RecordedLeader(raw)).route(
        [ChatMessage("user", "hello")], _profile()
    )
    assert decision.source == DecisionSource.DETERMINISTIC_FALLBACK
    assert decision.fallback_reason == FallbackReason.PLAN_REJECTED
    assert decision.plan_rejection == rejection
    assert decision.model_id in decision.candidates


@pytest.mark.anyio
async def test_unavailable_leader_is_explicit_and_deterministic(config_dir):
    class Down:
        model_id = "leader"
        rank = 0
        source = DecisionSource.LIVE_LEADER

        def projected_cost_usd(self, digest, candidate_count):
            return 0.01

        async def consult(self, digest, candidates):
            raise LeaderUnavailable("leader unavailable")

    decision = await _router(config_dir, Down()).route([ChatMessage("user", "hello")], _profile())
    assert decision.fallback_reason == FallbackReason.LEADER_UNAVAILABLE
    assert decision.attempts[0].outcome == "unavailable"
    assert not decision.frontier_authored


@pytest.mark.anyio
async def test_routing_budget_is_checked_before_consult(config_dir):
    class Exploding:
        model_id = "leader"
        rank = 0
        source = DecisionSource.LIVE_LEADER

        def projected_cost_usd(self, digest, candidate_count):
            return 0.01

        async def consult(self, digest, candidates):
            raise AssertionError("consult must not happen after budget exhaustion")

    decision = await _router(config_dir, Exploding(), budget=0.001).route(
        [ChatMessage("user", "hello")], _profile(), routing_spend_usd=0.001
    )
    assert decision.fallback_reason == FallbackReason.ROUTING_BUDGET_EXHAUSTED
    assert decision.attempts == ()
    assert decision.budget["projected_usd"] == 0.01


def test_runtime_router_rejects_invalid_budget(config_dir):
    with pytest.raises(ValueError, match="finite and non-negative"):
        _router(config_dir, None, budget=float("nan"))


@pytest.mark.anyio
async def test_runtime_decision_replays_without_reconsulting_leader(config_dir, tmp_path):
    leader = RecordedLeader('{"model_id":"gpt-4-1-mini@api:default"}')
    router = _router(config_dir, leader)
    decision = await router.route([ChatMessage("user", "hello")], _profile())
    body = ChatCompletionRequest.model_validate(
        {
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
            "router": {"runtime": True},
        }
    )
    ledger = SQLiteLedger(str(tmp_path / "replay.sqlite3"))
    request_id = "runtime-1"
    ledger.append(
        request_id,
        "started",
        {
            "request": body.model_dump(mode="json"),
            "model": decision.model_id,
            "registry_version": router.registry.version,
            "decision_version": decision.decision_version,
            "routing_decision": decision.to_payload(),
            "normalized_request": asdict(body.to_internal(decision.model_id)),
        },
    )
    replay = replay_request(ledger, request_id)
    assert replay["decision_matches"] is True
    assert replay["replay_source"] == "runtime_decision_snapshot"
    assert replay["frontier_authored"] is False
    ledger.close()
