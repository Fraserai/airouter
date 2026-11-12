"""Bounded execution with deterministic verification and escalation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from router_core.providers.base import ProviderError
from router_core.router.candidates import Candidate
from router_core.verifier.gates.core import (
    FailureClass,
    VerificationResult,
    VerificationStatus,
    verify_completion,
)
from router_core.verifier.gates.escalation import EscalationAction, next_escalation


@dataclass(frozen=True)
class ExecutionAttempt:
    model_id: str
    content: str | None
    finish_reason: str | None
    cost_usd: float | None
    tool_calls: tuple[dict, ...] = ()
    refusal: str | None = None


@dataclass(frozen=True)
class AttemptRecord:
    attempt: ExecutionAttempt
    verification: VerificationResult
    action_after: EscalationAction


@dataclass(frozen=True)
class ExecutionRun:
    status: VerificationStatus
    final: ExecutionAttempt | None
    attempts: tuple[AttemptRecord, ...]
    total_cost_usd: float | None
    stopped_reason: str | None = None


async def execute_with_escalation(
    candidates: Sequence[Candidate],
    initial_model_id: str,
    execute: Callable[[str], Awaitable[ExecutionAttempt]],
    *,
    response_schema: dict | None = None,
    task_class: str | None = None,
    max_escalations: int = 2,
    budget_usd: float | None = None,
    spent_usd: float = 0.0,
) -> ExecutionRun:
    """Execute, verify, and escalate at most ``max_escalations`` times.

    Unknown cost stops the run before another attempt. A deterministic gate
    failure may trigger the configured ladder; an unknown quality result does
    not justify spending more money without a declared contract.
    """
    if not candidates or initial_model_id not in {candidate.model_id for candidate in candidates}:
        raise ValueError("initial model must be an eligible candidate")
    if max_escalations < 0 or spent_usd < 0:
        raise ValueError("escalation limit and spend must be non-negative")
    if budget_usd is not None and (budget_usd < 0 or spent_usd > budget_usd):
        raise ValueError("spend must be within the execution budget")

    by_id = {candidate.model_id: candidate for candidate in candidates}
    current = by_id[initial_model_id]
    records: list[AttemptRecord] = []
    spent = spent_usd
    escalations = 0

    def next_candidate(action: EscalationAction, model: Candidate) -> Candidate | None:
        if action == EscalationAction.RETRY_SAME:
            return model
        if action == EscalationAction.EFFORT_UP:
            siblings = [
                candidate
                for candidate in candidates
                if candidate.family == model.family
                and candidate.placement == model.placement
                and candidate.effort_rank > model.effort_rank
            ]
            return min(
                siblings,
                key=lambda candidate: (candidate.effort_rank, candidate.projected_cost_usd),
                default=None,
            )
        if action == EscalationAction.FAMILY_UP:
            families = [candidate for candidate in candidates if candidate.family != model.family]
            return min(families, key=lambda candidate: candidate.projected_cost_usd, default=None)
        return None

    while True:
        if budget_usd is not None and spent + current.projected_cost_usd > budget_usd:
            return ExecutionRun(
                VerificationStatus.FAIL,
                None,
                tuple(records),
                spent,
                "execution_budget_exhausted",
            )
        try:
            attempt = await execute(current.model_id)
            verification = verify_completion(
                content=attempt.content,
                finish_reason=attempt.finish_reason,
                task_class=task_class,
                response_schema=response_schema,
                tool_calls=attempt.tool_calls,
                refusal=attempt.refusal,
            )
        except ProviderError:
            attempt = ExecutionAttempt(current.model_id, None, "provider_error", None)
            verification = VerificationResult(
                VerificationStatus.FAIL,
                {"provider_response": False},
                "executor provider error",
                FailureClass.PROVIDER_ERROR,
            )

        if attempt.cost_usd is None:
            records.append(AttemptRecord(attempt, verification, EscalationAction.NONE))
            return ExecutionRun(
                verification.status,
                attempt,
                tuple(records),
                None,
                "unknown_execution_cost",
            )
        if attempt.cost_usd < 0:
            records.append(AttemptRecord(attempt, verification, EscalationAction.NONE))
            return ExecutionRun(
                VerificationStatus.FAIL,
                attempt,
                tuple(records),
                None,
                "invalid_execution_cost",
            )
        if budget_usd is not None and spent + attempt.cost_usd > budget_usd:
            records.append(AttemptRecord(attempt, verification, EscalationAction.NONE))
            return ExecutionRun(
                VerificationStatus.FAIL,
                attempt,
                tuple(records),
                spent,
                "execution_budget_exhausted",
            )
        spent += attempt.cost_usd
        if verification.status in {VerificationStatus.PASS, VerificationStatus.UNKNOWN}:
            records.append(AttemptRecord(attempt, verification, EscalationAction.NONE))
            return ExecutionRun(verification.status, attempt, tuple(records), spent)

        action = next_escalation(
            verification.failure_class, escalations, max_escalations=max_escalations
        )
        records.append(AttemptRecord(attempt, verification, action))
        if action == EscalationAction.NONE:
            return ExecutionRun(
                VerificationStatus.FAIL, attempt, tuple(records), spent, "escalation_limit"
            )
        candidate = next_candidate(action, current)
        if candidate is None:
            return ExecutionRun(
                VerificationStatus.FAIL, attempt, tuple(records), spent, "no_escalation_candidate"
            )
        if budget_usd is not None and spent + candidate.projected_cost_usd > budget_usd:
            return ExecutionRun(
                VerificationStatus.FAIL,
                attempt,
                tuple(records),
                spent,
                "execution_budget_exhausted",
            )
        current = candidate
        escalations += 1
