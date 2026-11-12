import pytest

from router_core.providers.base import ProviderError
from router_core.router.candidates import Candidate
from router_core.verifier import (
    EscalationAction,
    ExecutionAttempt,
    VerificationStatus,
    execute_with_escalation,
)


def _candidate(model, family, rank, cost):
    return Candidate(model, family, "effort", rank, "cloud_open", 1000, cost, {})


@pytest.mark.anyio
async def test_underthinking_escalates_effort_then_passes():
    candidates = [
        _candidate("cheap-low", "same", 0, 0.01),
        _candidate("cheap-high", "same", 1, 0.02),
    ]
    calls = []

    async def execute(model):
        calls.append(model)
        return ExecutionAttempt(
            model,
            '{"answer":"ok"}' if model == "cheap-high" else "partial",
            "stop" if model == "cheap-high" else "length",
            0.01,
        )

    result = await execute_with_escalation(
        candidates,
        "cheap-low",
        execute,
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    assert calls == ["cheap-low", "cheap-high"]
    assert result.status == VerificationStatus.PASS
    assert result.attempts[0].action_after == EscalationAction.EFFORT_UP
    assert result.total_cost_usd == pytest.approx(0.02)


@pytest.mark.anyio
async def test_capability_failure_switches_family():
    candidates = [_candidate("family-a", "a", 0, 0.01), _candidate("family-b", "b", 0, 0.03)]
    calls = []

    async def execute(model):
        calls.append(model)
        return ExecutionAttempt(
            model, '{"answer":4}' if model == "family-a" else '{"answer":"ok"}', "stop", 0.01
        )

    result = await execute_with_escalation(
        candidates,
        "family-a",
        execute,
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    assert calls == ["family-a", "family-b"]
    assert result.status == VerificationStatus.PASS
    assert result.attempts[0].action_after == EscalationAction.FAMILY_UP


@pytest.mark.anyio
async def test_budget_blocks_before_provider_call():
    called = False

    async def execute(model):
        nonlocal called
        called = True
        return ExecutionAttempt(model, "ok", "stop", 0.01)

    result = await execute_with_escalation(
        [_candidate("model", "family", 0, 0.10)],
        "model",
        execute,
        budget_usd=0.05,
    )
    assert called is False
    assert result.stopped_reason == "execution_budget_exhausted"


@pytest.mark.anyio
async def test_unknown_cost_stops_without_escalating():
    candidates = [_candidate("first", "a", 0, 0.01), _candidate("second", "b", 0, 0.02)]

    async def execute(model):
        return ExecutionAttempt(model, "answer", "length", None)

    result = await execute_with_escalation(candidates, "first", execute)
    assert result.status == VerificationStatus.FAIL
    assert result.stopped_reason == "unknown_execution_cost"
    assert len(result.attempts) == 1


@pytest.mark.anyio
async def test_provider_error_stops_when_cost_is_unknown():
    async def execute(model):
        raise ProviderError("temporary", retryable=True)

    result = await execute_with_escalation(
        [_candidate("model", "family", 0, 0.01)], "model", execute, max_escalations=1
    )
    assert result.status == VerificationStatus.FAIL
    assert result.stopped_reason == "unknown_execution_cost"
    assert len(result.attempts) == 1
