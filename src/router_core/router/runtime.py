"""Runtime routing orchestration.

The leader proposes a destination; this module decides whether that proposal is
allowed to run. Candidate filtering and plan validation are deterministic. A
fallback is explicit in the returned decision and is never labelled as frontier
authorship.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from router_core.providers.base import ChatMessage
from router_core.registry.store import Registry
from router_core.router.candidates import (
    Candidate,
    RequestProfile,
    cheapest,
    filter_candidates,
)
from router_core.router.digest import DigestLimits, RequestDigest, build_digest
from router_core.router.leader import LeaderUnavailable, RoutingLeader
from router_core.router.protocol import (
    DecisionSource,
    FallbackReason,
    LeaderAttempt,
    PlanRejection,
    RoutingDecision,
    RoutingError,
    validate_plan,
)


@dataclass(frozen=True)
class RuntimeRoutingConfig:
    """Limits and deterministic tie-breaks for one routing window."""

    digest_limits: DigestLimits = DigestLimits(max_tokens=2000, head_chars=3200, tail_chars=3200)
    spend_budget_usd: float = 0.0
    placement_preference: tuple[str, ...] = ("local", "cloud_open", "closed_frontier")
    require_leader: bool = False


class RuntimeRouter:
    """Choose one eligible executor using an optional runtime leader."""

    def __init__(
        self,
        registry: Registry,
        *,
        leader: RoutingLeader | None,
        quality_floors: dict | None = None,
        config: RuntimeRoutingConfig | None = None,
        catalog: Registry | None = None,
    ):
        self.registry = registry
        self.leader = leader
        self.quality_floors = quality_floors or {}
        self.config = config or RuntimeRoutingConfig()
        self.catalog = catalog
        if not math.isfinite(self.config.spend_budget_usd) or self.config.spend_budget_usd < 0:
            raise ValueError("routing spend budget must be finite and non-negative")

    def _fallback(
        self,
        chosen: Candidate,
        candidates: Sequence[Candidate],
        excluded: dict[str, tuple[str, ...]],
        digest: RequestDigest,
        reason: FallbackReason,
        *,
        attempts: tuple[LeaderAttempt, ...] = (),
        plan_rejection: PlanRejection | None = None,
        plan_rejection_detail: str | None = None,
        budget: dict | None = None,
    ) -> RoutingDecision:
        # A rejected plan can still be a paid consultation. No consultation is
        # known zero; a failed call without usage leaves the charge unknown.
        cost_known = all(
            attempt.cost_known
            and isinstance(attempt.cost_usd, (int, float))
            and not isinstance(attempt.cost_usd, bool)
            and math.isfinite(attempt.cost_usd)
            and attempt.cost_usd >= 0
            for attempt in attempts
        )
        cost = (
            float(sum((Decimal(str(a.cost_usd)) for a in attempts), Decimal(0)))
            if cost_known
            else None
        )
        decision = RoutingDecision(
            model_id=chosen.model_id,
            source=DecisionSource.DETERMINISTIC_FALLBACK,
            reason=f"deterministic fallback: {reason.value}",
            candidates=tuple(c.model_id for c in candidates),
            excluded=excluded,
            fallback_reason=reason,
            plan_rejection=plan_rejection,
            plan_rejection_detail=plan_rejection_detail,
            attempts=attempts,
            routing_cost_usd=cost,
            routing_cost_known=cost_known,
            digest_tokens=digest.tokens,
            digest_bounded=digest.tokens <= self.config.digest_limits.max_tokens,
            budget=budget or {},
        )
        if self.config.require_leader:
            raise RoutingError(
                "routing intelligence could not author a valid decision",
                code="routing_intelligence_unavailable",
                detail={"routing_decision": decision.to_payload()},
            )
        return decision

    def _digest(
        self,
        messages: Sequence[ChatMessage],
        profile: RequestProfile,
        *,
        tool_names: Sequence[str] = (),
        response_format: str | None = None,
    ) -> RequestDigest:
        return build_digest(
            messages,
            limits=self.config.digest_limits,
            requested_max_tokens=profile.max_output_tokens,
            tool_names=tool_names,
            response_format=response_format,
            task_class=profile.task_class,
        )

    async def route(
        self,
        messages: Sequence[ChatMessage],
        profile: RequestProfile,
        *,
        tool_names: Sequence[str] = (),
        response_format: str | None = None,
        routing_spend_usd: float = 0.0,
        consult_leader: bool = True,
    ) -> RoutingDecision:
        """Return a decision, charging only actual leader consultations.

        The caller owns the durable ledger write. ``routing_spend_usd`` is the
        already committed amount in the current window, so this method can
        refuse a consult before making a paid call.
        """
        if not math.isfinite(routing_spend_usd) or routing_spend_usd < 0:
            raise ValueError("routing spend must be finite and non-negative")
        eligible, excluded = filter_candidates(self.registry, profile, self.quality_floors)
        if self.catalog is not None:
            references = {entry.family: entry for entry in self.catalog.ranked()}
            eligible = [
                replace(
                    candidate,
                    market_reference={
                        "model": reference.display_name,
                        "intelligence_index": reference.scores.composite,
                        "snapshot_date": str(reference.scores.measured_at),
                        "source": reference.scores.source,
                        "configuration_verified": False,
                        "usage": "aggregate prior only; not measured workload quality",
                    },
                )
                if (reference := references.get(candidate.family))
                else candidate
                for candidate in eligible
            ]
        if not eligible:
            raise RoutingError(
                "no eligible executor satisfies the request constraints",
                code="no_eligible_candidates",
                detail={"excluded": {k: list(v) for k, v in excluded.items()}},
            )

        digest = self._digest(
            messages, profile, tool_names=tool_names, response_format=response_format
        )
        if not consult_leader:
            # A preview may list feasible models, but cannot predict a live choice.
            preview = RuntimeRouter(
                self.registry,
                leader=None,
                config=replace(self.config, require_leader=False),
            )
            return preview._fallback(
                cheapest(eligible, list(self.config.placement_preference)),
                eligible,
                excluded,
                digest,
                FallbackReason.LEADER_DISABLED,
            )
        chosen = cheapest(eligible, list(self.config.placement_preference))
        if len(eligible) == 1 and (not consult_leader or self.leader is None):
            return self._fallback(
                chosen,
                eligible,
                excluded,
                digest,
                FallbackReason.SINGLE_CANDIDATE,
                budget={"spent_usd": routing_spend_usd, "limit_usd": self.config.spend_budget_usd},
            )
        if not consult_leader or self.leader is None:
            return self._fallback(
                chosen,
                eligible,
                excluded,
                digest,
                FallbackReason.LEADER_UNAVAILABLE,
                budget={"spent_usd": routing_spend_usd, "limit_usd": self.config.spend_budget_usd},
            )

        projected = self.leader.projected_cost_usd(digest, eligible)
        budget = {
            "spent_usd": routing_spend_usd,
            "limit_usd": self.config.spend_budget_usd,
            "projected_usd": projected,
        }
        if (
            projected is None
            or not math.isfinite(projected)
            or projected < 0
            or routing_spend_usd + projected > self.config.spend_budget_usd
        ):
            return self._fallback(
                chosen,
                eligible,
                excluded,
                digest,
                FallbackReason.ROUTING_BUDGET_EXHAUSTED,
                budget=budget,
            )

        if profile.max_cost_usd is not None:
            # Reserve the routing consultation before offering executors.
            remaining = profile.max_cost_usd - projected
            affordable = []
            for candidate in eligible:
                if candidate.projected_cost_usd <= remaining:
                    affordable.append(candidate)
                else:
                    excluded[candidate.model_id] = ("over_total_cost_with_routing",)
            if not affordable:
                raise RoutingError(
                    "estimated routing and execution exceed the request cost limit",
                    code="request_cost_limit",
                    detail={
                        "projected_routing_cost_usd": projected,
                        "max_cost_usd": profile.max_cost_usd,
                    },
                )
            eligible = affordable
            chosen = cheapest(eligible, list(self.config.placement_preference))
            budget = {
                **budget,
                "request_limit_usd": profile.max_cost_usd,
                "execution_allowance_usd": remaining,
            }

        try:
            response = await self.leader.consult(digest, eligible)
        except LeaderUnavailable as exc:
            attempt = LeaderAttempt(
                self.leader.model_id,
                self.leader.rank,
                "unavailable",
                latency_ms=None,
                detail=str(exc)[:200],
            )
            return self._fallback(
                chosen,
                eligible,
                excluded,
                digest,
                FallbackReason.LEADER_UNAVAILABLE,
                attempts=(attempt,),
                budget=budget,
            )

        attempt = LeaderAttempt(
            response.model_id,
            response.rank,
            "consulted",
            cost_usd=response.cost_usd,
            cost_known=response.cost_known,
            latency_ms=response.latency_ms,
        )
        plan, rejection, detail = validate_plan(
            response.raw_text, {candidate.model_id for candidate in eligible}
        )
        if plan is None:
            return self._fallback(
                chosen,
                eligible,
                excluded,
                digest,
                FallbackReason.PLAN_REJECTED,
                attempts=(attempt,),
                plan_rejection=rejection,
                plan_rejection_detail=detail,
                budget={**budget, "actual_usd": response.cost_usd},
            )

        return RoutingDecision(
            model_id=plan.model_id,
            source=response.source,
            reason="leader-selected eligible candidate",
            candidates=tuple(candidate.model_id for candidate in eligible),
            excluded=excluded,
            leader_model_id=response.model_id,
            leader_rank=response.rank,
            leader_reason=plan.reason,
            confidence=plan.confidence,
            routing_cost_usd=response.cost_usd,
            routing_cost_known=response.cost_known,
            attempts=(attempt,),
            digest_tokens=digest.tokens,
            digest_bounded=digest.tokens <= self.config.digest_limits.max_tokens,
            budget={**budget, "actual_usd": response.cost_usd},
        )


__all__ = ["RuntimeRouter", "RuntimeRoutingConfig"]
