"""Cost provenance across paid routing failures and executor outcomes."""

import json

import pytest

from router_core.ledger.store import SQLiteLedger
from router_core.providers.base import ChatMessage
from router_core.registry.schema import ModelEntry
from router_core.registry.store import Registry
from router_core.router.candidates import RequestProfile
from router_core.router.leader import LeaderResponse, LeaderUnavailable, RecordedLeader
from router_core.router.protocol import DecisionSource, FallbackReason
from router_core.router.runtime import RuntimeRouter, RuntimeRoutingConfig


def _registry(count=2):
    return Registry([
        ModelEntry.model_validate({
            "id": f"executor-{index}", "display_name": f"Executor {index}",
            "access": "open", "placement": "cloud_open", "lifecycle": "executor",
            "verified": True, "context_window": 10000,
            "pricing": {"input_usd_per_mtok": 1, "output_usd_per_mtok": 1},
            "cost": {
                "basis": "per_token", "marginal_input_usd_per_mtok": 1,
                "marginal_output_usd_per_mtok": 1, "allocated_input_usd_per_mtok": 1,
                "allocated_output_usd_per_mtok": 1,
            },
        })
        for index in range(count)
    ])


class FakePaidLeader:
    model_id = "test-leader"
    rank = 1
    source = DecisionSource.LIVE_LEADER

    def __init__(self, raw="not json", *, cost=0.02, known=True, unavailable=False):
        self.raw = raw
        self.cost = cost
        self.known = known
        self.unavailable = unavailable
        self.calls = 0

    def projected_cost_usd(self, digest, candidates):
        return 0.03

    async def consult(self, digest, candidates):
        self.calls += 1
        if self.unavailable:
            raise LeaderUnavailable("response lost")
        return LeaderResponse(
            self.raw, self.model_id, self.rank, self.source, self.cost, self.known, 1.0
        )


async def _decision(leader, *, budget=1, count=2):
    return await RuntimeRouter(
        _registry(count), leader=leader,
        config=RuntimeRoutingConfig(spend_budget_usd=budget),
    ).route([ChatMessage("user", "Summarize this")], RequestProfile(20, 20))


@pytest.mark.anyio
@pytest.mark.parametrize("raw", ["not json", '{"model_id": "not-offered"}'])
async def test_paid_rejected_plan_keeps_routing_charge(raw):
    decision = await _decision(FakePaidLeader(raw))
    assert decision.fallback_reason == FallbackReason.PLAN_REJECTED
    assert not decision.frontier_authored
    assert decision.routing_cost_usd == 0.02
    assert decision.routing_cost_known is True


@pytest.mark.anyio
async def test_no_consult_is_known_zero_including_budget_refusal():
    leader = FakePaidLeader()
    for decision in (await _decision(None), await _decision(leader, budget=0)):
        assert decision.attempts == ()
        assert decision.routing_cost_usd == 0.0
        assert decision.routing_cost_known is True
    assert leader.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_uncertain_consult_cost_stays_unknown(unavailable):
    decision = await _decision(FakePaidLeader(cost=None, known=False, unavailable=unavailable))
    assert decision.routing_cost_usd is None
    assert decision.routing_cost_known is False
    assert len(decision.attempts) == 1


@pytest.mark.anyio
async def test_configured_leader_still_decides_with_single_executor():
    live = FakePaidLeader(json.dumps({"model_id": "executor-0"}))
    recorded = RecordedLeader('{"model_id": "executor-0"}')
    for leader in (live, recorded):
        decision = await _decision(leader, count=1)
        assert decision.source == leader.source
        assert len(decision.attempts) == 1
    assert live.calls == 1


@pytest.fixture
def ledger():
    store = SQLiteLedger(":memory:")
    yield store
    store.close()


def _started(cost, *, access="open", placement="cloud_open", known=True):
    return {
        "decision": "runtime", "routing_cost_usd": cost,
        "model_snapshot": {"id": "executor", "access": access, "placement": placement},
        "routing_decision": {
            "decision_source": "live_leader", "leader_model": "test-leader",
            "routing_cost_usd": cost, "routing_cost_known": known,
            "attempts": [{"cost_usd": cost, "cost_known": known}],
        },
    }


def test_started_charge_is_visible_and_terminal_copy_does_not_double_bill(ledger):
    ledger.append("request", "started", _started(0.02))
    assert ledger.routing_spend_usd() == 0.02
    in_flight = ledger.stats()
    assert in_flight["known_total_cost_usd"] == 0.02
    assert in_flight["total_cost_usd"] is None
    assert in_flight["unfinished"] == 1

    ledger.append("request", "completed", {"routing_cost_usd": 0.02, "execution_cost_usd": 0.03})
    stats = ledger.stats()
    assert ledger.routing_spend_usd() == 0.02
    assert stats["known_execution_cost_usd"] == 0.03
    assert stats["known_routing_cost_usd"] == 0.02
    assert stats["total_cost_usd"] == 0.05
    assert stats["spend_complete"] is True
    assert stats["routing_implemented"] is True


def test_unknown_router_cost_cannot_be_reported_as_complete_bill(ledger):
    ledger.append("request", "started", _started(None, known=False))
    ledger.append("request", "completed", {"execution_cost_usd": 0.03})
    stats = ledger.stats()
    assert stats["known_total_cost_usd"] == 0.03
    assert stats["unknown_routing_cost_requests"] == 1
    assert stats["routing_spend_complete"] is False
    assert stats["spend_complete"] is False
    assert stats["total_cost_usd"] is None


def test_historical_rejected_plan_charge_is_recovered_from_attempts(ledger):
    started = _started(0.02)
    started["routing_cost_usd"] = None
    decision = started["routing_decision"]
    decision.update({
        "decision_source": "deterministic_fallback", "routing_cost_usd": None,
        "routing_cost_known": False,
    })
    ledger.append("request", "started", started)
    ledger.append("request", "failed", {"routing_cost_usd": None, "execution_cost_usd": None})
    assert ledger.routing_spend_usd() == 0.02
    assert ledger.stats()["known_routing_cost_usd"] == 0.02
    assert ledger.stats()["unknown_cost_requests"] == 1
    assert ledger.stats()["spend_complete"] is False


def test_execution_mix_uses_snapshots_excludes_leader_and_keeps_unknown_access(ledger):
    for index, (access, placement) in enumerate([
        ("open", "cloud_open"), ("open", "local"),
        ("closed", "closed_frontier"), ("unknown", "local"),
    ]):
        ledger.append(str(index), "started", _started(0.01, access=access, placement=placement))
        ledger.append(str(index), "completed", {"execution_cost_usd": 0.02})
    mix = ledger.stats()["execution_mix"]
    assert mix["requests"] == 4
    assert mix["by_access"]["open"]["share"] == 0.5
    assert mix["by_access"]["closed"]["requests"] == 1
    assert mix["by_access"]["unknown"]["requests"] == 1
    assert mix["by_placement"]["local"]["requests"] == 2
    assert mix["by_access"]["open"]["known_execution_cost_usd"] == 0.04
    assert ledger.stats()["known_routing_cost_usd"] == 0.04


def test_legacy_fixed_request_has_no_router_charge(ledger):
    ledger.append("fixed", "started", {"decision": "fixed_model", "routing_cost_usd": None})
    ledger.append("fixed", "completed", {"execution_cost_usd": 0.1, "routing_cost_usd": None})
    stats = ledger.stats()
    assert stats["runtime_routed_requests"] == 0
    assert stats["known_routing_cost_usd"] == 0
    assert stats["spend_complete"] is True


def test_unsupported_event_and_duplicate_terminal_do_not_inflate_charges(ledger):
    ledger.append("a", "started", _started(0.01))
    ledger.append("a", "progress", {"execution_cost_usd": 100})
    for _ in range(2):
        ledger.append("a", "completed", {"execution_cost_usd": 0.02})
    stats = ledger.stats()
    assert stats["completed"] == 1
    assert stats["unfinished"] == 0
    assert stats["known_total_cost_usd"] == 0.03


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, True])
def test_invalid_recorded_charge_is_unknown(ledger, invalid):
    ledger.append("a", "started", _started(invalid))
    ledger.append("a", "completed", {"execution_cost_usd": invalid})
    stats = ledger.stats()
    assert stats["known_total_cost_usd"] == 0
    assert stats["total_cost_usd"] is None
    assert stats["unknown_routing_cost_requests"] == 1
