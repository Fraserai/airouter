"""Who is even allowed to serve this request.

This filter runs BEFORE any model is asked anything, and its output is the only
menu the leader ever sees. That ordering is the whole safety argument: a leader
cannot select an unverified, unpriced, policy-forbidden or capability-short
model because it is never shown one.

An entry with no measurement is excluded, not assumed adequate. A missing score
is an absence of evidence, and routing on absent evidence is how a quality floor
quietly becomes a suggestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from router_core.costing.pricing import estimate_usd
from router_core.registry.schema import ModelEntry
from router_core.registry.store import Registry


@dataclass(frozen=True)
class RequestProfile:
    """Everything eligibility depends on, extracted from the request.

    `input_tokens` is an ESTIMATE (no tokeniser is available before a provider
    is chosen). It is used for context-window headroom and for projecting cost,
    both of which stay conservative under a small overestimate.
    """

    input_tokens: int
    max_output_tokens: int
    required_features: frozenset[str] = frozenset()
    task_class: str | None = None
    placement_allow: frozenset[str] | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class Candidate:
    model_id: str
    family: str
    effort: str
    effort_rank: int
    placement: str
    context_window: int | None
    projected_cost_usd: float
    capability: dict[str, float]
    market_reference: dict[str, Any] = field(default_factory=dict)

    def to_offer(self) -> dict[str, Any]:
        """The candidate as shown to a leader. No vendor identity beyond the id,
        no benchmark economics, no free-text marketing -- just what it can do,
        what it costs on THIS request, and where it runs."""
        return {
            "model": self.model_id,
            "effort": self.effort,
            "effort_rank": self.effort_rank,
            "placement": self.placement,
            "context_window": self.context_window,
            "projected_cost_usd": round(self.projected_cost_usd, 8),
            "capability": self.capability,
            "market_reference": self.market_reference,
        }


def _capability_floor(floors: dict[str, Any], task_class: str | None) -> dict[str, float]:
    if not task_class:
        return {}
    classes = floors.get("task_classes") or {}
    return dict((classes.get(task_class) or {}).get("capability") or {})


def _context_reasons(entry: ModelEntry, profile: RequestProfile) -> list[str]:
    if entry.context_window is None:
        return ["context_window_unknown"]
    if profile.input_tokens + profile.max_output_tokens > entry.context_window:
        return ["context_overflow"]
    return []


def evaluate_entry(
    entry: ModelEntry,
    profile: RequestProfile,
    floor: dict[str, float],
) -> tuple[Candidate | None, list[str]]:
    """Return the candidate, or the reasons it may not serve this request."""
    reasons = list(entry.selectable_reasons())

    if profile.placement_allow is not None and entry.placement.value not in profile.placement_allow:
        reasons.append("placement_not_allowed")

    for feature in sorted(profile.required_features):
        if feature not in entry.api_features:
            reasons.append(f"missing_feature:{feature}")

    reasons.extend(_context_reasons(entry, profile))

    capability: dict[str, float] = {
        key: value
        for key, value in entry.scores.model_dump().items()
        if isinstance(value, (int, float))
    }
    for key, minimum in sorted(floor.items()):
        score = entry.scores.get_eval(key)
        if score is None:
            # Unmeasured is not "probably fine". See module docstring.
            reasons.append(f"capability_unmeasured:{key}")
        elif score < minimum:
            reasons.append(f"capability_below_floor:{key}")
        else:
            capability[key] = score

    projected: float | None = None
    if entry.cost is not None:
        # marginal=True: this is a routing decision, not a report. The two rates
        # diverge for amortised placements and swapping them is the single
        # easiest way to break the economics.
        projected = estimate_usd(
            entry.cost, profile.input_tokens, profile.max_output_tokens, marginal=True
        )
        if profile.max_cost_usd is not None and projected > profile.max_cost_usd:
            reasons.append("over_max_cost")

    if reasons or projected is None:
        return None, reasons or ["no_projected_cost"]

    return (
        Candidate(
            model_id=entry.id,
            family=entry.family or entry.id,
            effort=entry.effort,
            effort_rank=entry.effort_rank,
            placement=entry.placement.value,
            context_window=entry.context_window,
            projected_cost_usd=projected,
            capability=capability,
        ),
        [],
    )


def filter_candidates(
    registry: Registry,
    profile: RequestProfile,
    quality_floors: dict[str, Any],
) -> tuple[list[Candidate], dict[str, tuple[str, ...]]]:
    """The eligible pool, plus why everything else was excluded.

    The exclusion map is not diagnostics padding: `explain: true` has to be able
    to tell an operator why their model was not chosen, and "it wasn't offered"
    is only a usable answer if the reason survives with it.
    """
    floor = _capability_floor(quality_floors, profile.task_class)
    eligible: list[Candidate] = []
    excluded: dict[str, tuple[str, ...]] = {}
    for entry in sorted(registry.all(), key=lambda e: e.id):
        candidate, reasons = evaluate_entry(entry, profile, floor)
        if candidate is not None:
            eligible.append(candidate)
        else:
            excluded[entry.id] = tuple(reasons)
    return eligible, excluded


def cheapest(candidates: list[Candidate], placement_preference: list[str]) -> Candidate:
    """Deterministic choice: lowest projected marginal cost on this request.

    Ties break on configured placement order, then model id, so the same inputs
    always give the same answer -- a fallback that wanders is unreplayable.
    """
    order = {name: i for i, name in enumerate(placement_preference)}
    return min(
        candidates,
        key=lambda c: (
            c.projected_cost_usd,
            order.get(c.placement, len(order)),
            c.model_id,
        ),
    )
