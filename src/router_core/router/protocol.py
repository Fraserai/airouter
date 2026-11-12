"""The routing decision contract.

Two rules shape this module, both from the approved architecture:

  1. A model's output is a PROPOSAL. Deterministic code decides whether it is
     allowed to become a decision. Nothing the leader emits can widen the
     candidate set, raise a budget or bypass a constraint -- the plan schema
     is closed (`extra="forbid"`) and carries no executable fields.

  2. Every decision must say WHO made it. A fallback that reads like frontier
     reasoning is the failure mode that would make the product's central claim
     unfalsifiable, so provenance is a required field on the record, not an
     optional annotation, and `frontier_authored` is computed here rather than
     written by any caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DECISION_VERSION = "runtime-v1"


class DecisionSource(StrEnum):
    """Who actually chose the model. Recorded on every request."""

    #: A live consult with a configured leader model.
    LIVE_LEADER = "live_leader"
    #: A canned decision replayed from a fixture. Deterministic, never live.
    RECORDED_LEADER = "recorded_leader"
    #: Deterministic code chose, because no leader decided. Never a "plan".
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class FallbackReason(StrEnum):
    LEADER_DISABLED = "leader_disabled"
    LEADER_UNAVAILABLE = "leader_unavailable"
    ROUTING_BUDGET_EXHAUSTED = "routing_budget_exhausted"
    PLAN_REJECTED = "plan_rejected"
    SINGLE_CANDIDATE = "single_candidate"


class PlanRejection(StrEnum):
    """Why deterministic validation refused a leader's plan."""

    EMPTY_RESPONSE = "empty_response"
    MALFORMED_JSON = "malformed_json"
    SCHEMA_INVALID = "schema_invalid"
    UNKNOWN_MODEL = "unknown_model"
    MODEL_NOT_OFFERED = "model_not_offered"


class LeaderPlan(BaseModel):
    """Exactly what a leader is allowed to say.

    Deliberately tiny. Every additional field is another thing a model could
    assert that deterministic code would then have to disprove; the candidate
    list it chooses from was already constrained before it was asked.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=600)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RoutingError(RuntimeError):
    """Routing could not produce an allowed model."""

    def __init__(self, message: str, *, code: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


@dataclass(frozen=True)
class LeaderAttempt:
    """One consult attempt, successful or not. Kept for audit and for cost."""

    model_id: str
    rank: int
    outcome: str
    cost_usd: float | None = None
    cost_known: bool = False
    latency_ms: float | None = None
    detail: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "model": self.model_id,
            "rank": self.rank,
            "outcome": self.outcome,
            "cost_usd": self.cost_usd,
            "cost_known": self.cost_known,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RoutingDecision:
    """The auditable result of one routing decision.

    `routing_cost_usd` is the cost of DECIDING. It is never added to execution
    cost here: the two are reported as separate lines and summed only by the
    caller that is explicitly computing total economics.
    """

    model_id: str
    source: DecisionSource
    reason: str
    candidates: tuple[str, ...]
    excluded: dict[str, tuple[str, ...]] = field(default_factory=dict)
    leader_model_id: str | None = None
    leader_rank: int | None = None
    leader_reason: str | None = None
    confidence: float | None = None
    fallback_reason: FallbackReason | None = None
    plan_rejection: PlanRejection | None = None
    plan_rejection_detail: str | None = None
    routing_cost_usd: float | None = None
    routing_cost_known: bool = False
    attempts: tuple[LeaderAttempt, ...] = ()
    digest_tokens: int = 0
    digest_bounded: bool = True
    budget: dict[str, Any] = field(default_factory=dict)
    decision_version: str = DECISION_VERSION

    @property
    def frontier_authored(self) -> bool:
        """True only when a live leader consult produced this selection.

        Computed, never assigned. A recorded plan and a deterministic fallback
        are both false, which is what stops either from being reported as
        frontier reasoning.
        """
        return self.source == DecisionSource.LIVE_LEADER

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision_version": self.decision_version,
            "model": self.model_id,
            "decision_source": self.source.value,
            "frontier_authored": self.frontier_authored,
            "reason": self.reason,
            "leader_model": self.leader_model_id,
            "leader_rank": self.leader_rank,
            "leader_reason": self.leader_reason,
            "confidence": self.confidence,
            "fallback_reason": self.fallback_reason.value if self.fallback_reason else None,
            "plan_rejection": self.plan_rejection.value if self.plan_rejection else None,
            "plan_rejection_detail": self.plan_rejection_detail,
            "routing_cost_usd": self.routing_cost_usd,
            "routing_cost_known": self.routing_cost_known,
            "candidates": list(self.candidates),
            "candidate_count": len(self.candidates),
            "excluded": {k: list(v) for k, v in self.excluded.items()},
            "attempts": [a.to_payload() for a in self.attempts],
            "digest_tokens": self.digest_tokens,
            "digest_bounded": self.digest_bounded,
            "budget": self.budget,
        }


def validate_plan(
    raw_text: str, offered: set[str]
) -> tuple[LeaderPlan | None, PlanRejection | None, str | None]:
    """Turn a leader's raw output into a plan, or refuse it with a reason.

    Deterministic and total: every path returns either a plan whose `model_id`
    is provably one of the ids we offered, or a rejection. There is no branch
    that trusts the text. `offered` is the exact candidate list from this
    request, not the registry -- a model that is real but was not on the menu
    is still refused, because the menu is where the constraints were applied.
    """
    text = (raw_text or "").strip()
    if not text:
        return None, PlanRejection.EMPTY_RESPONSE, None

    # Tolerate a code fence around otherwise valid JSON. Tolerating formatting
    # is not the same as tolerating content: everything below still applies.
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    try:
        parsed = json.loads(text)
    except ValueError as exc:
        return None, PlanRejection.MALFORMED_JSON, str(exc)[:200]

    if not isinstance(parsed, dict):
        return None, PlanRejection.SCHEMA_INVALID, "top level must be an object"

    try:
        plan = LeaderPlan.model_validate(parsed)
    except ValidationError as exc:
        return None, PlanRejection.SCHEMA_INVALID, str(exc.errors()[0].get("msg", ""))[:200]

    if plan.model_id not in offered:
        # Both cases are refusals. They are distinguished because they mean
        # different things operationally: an id we have never heard of is a
        # hallucination, an id we know but did not offer is a constraint the
        # leader tried to route around.
        rejection = PlanRejection.MODEL_NOT_OFFERED if offered else PlanRejection.UNKNOWN_MODEL
        return None, rejection, plan.model_id[:200]

    return plan, None, None
