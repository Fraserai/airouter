"""Registry schema.

A single index score is not a capability profile (BRIEF.md §3 rule 3). The
schema carries all ten sub-evals from day one even though the seed file only
supplies the composite, because routing decisions are capability-specific.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The ten evaluations behind the composite index. Named here, in config-facing
# terms only -- no routing logic may branch on any individual key.
EVAL_KEYS: tuple[str, ...] = (
    "aa_briefcase",
    "gdpval_aa_v2",
    "tau3_banking",
    "terminal_bench_v2_1",
    "scicode",
    "hle",
    "gdp_pdf",
    "critpt",
    "aa_omniscience",
    "aa_lcr_v1_1",
)


class Placement(StrEnum):
    LOCAL = "local"
    CLOUD_OPEN = "cloud_open"
    CLOSED_FRONTIER = "closed_frontier"
    UNKNOWN = "unknown"

    @property
    def is_open(self) -> bool:
        """Whether this placement runs an open model; never a routing quota."""
        return self in (Placement.LOCAL, Placement.CLOUD_OPEN)


class Access(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class Lifecycle(StrEnum):
    """candidate -> executor -> router -> executor -> deprecated.

    `quarantined` is ours, not the brief's: a model suspected of silent
    degradation is a suspicion, not a decision, and `deprecated` is a decision.
    (PLAN.md Q5)
    """

    CANDIDATE = "candidate"
    EXECUTOR = "executor"
    ROUTER = "router"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"


class HealthState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class Scores(BaseModel):
    """Composite plus the ten sub-evals. Every field may be None."""

    model_config = ConfigDict(extra="forbid")

    composite: float | None = None
    measured_at: date | None = None
    source: str | None = None

    aa_briefcase: float | None = None
    gdpval_aa_v2: float | None = None
    tau3_banking: float | None = None
    terminal_bench_v2_1: float | None = None
    scicode: float | None = None
    hle: float | None = None
    gdp_pdf: float | None = None
    critpt: float | None = None
    aa_omniscience: float | None = None
    aa_lcr_v1_1: float | None = None

    def get_eval(self, key: str) -> float | None:
        if key not in EVAL_KEYS and key != "composite":
            raise KeyError(f"unknown eval key: {key}")
        return getattr(self, key)

    @property
    def has_subscores(self) -> bool:
        return any(getattr(self, k) is not None for k in EVAL_KEYS)


class Pricing(BaseModel):
    """Per-token pricing. Null until verified against the provider.

    `local` entries legitimately have no pricing -- their cost comes from the
    amortised model in costing/local_amortised.py.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)
    cached_input_usd_per_mtok: float | None = Field(default=None, ge=0)
    cache_write_input_usd_per_mtok: float | None = Field(default=None, ge=0)
    # Beyond this bound a separate long-context tariff needs verification.
    max_priced_input_tokens: int | None = Field(default=None, gt=0)
    currency: str = "USD"


class CostStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class Benchmark(BaseModel):
    """Published benchmark economics. NOT a price and NOT a routing input.

    `cost_per_task_usd` is a weighted average over the index provider's own task
    mix. It is only a valid predictor of YOUR cost if your traffic looks like
    their benchmark, which it will not. Routing prices requests from
    `TokenCost` x the request's own token profile. This block exists to seed
    priors, to sanity-check the harness, and for display.

    `index_per_usd` is a browsing aid. A model with a great ratio that sits below
    the task's capability floor is useless at any price.

    tests/test_selection_guards.py asserts nothing in the selection path reads it.
    """

    model_config = ConfigDict(extra="forbid")

    cost_per_task_usd: float | None = None
    cost_status: CostStatus = CostStatus.UNKNOWN
    source: str | None = None
    measured_at: date | None = None

    @property
    def index_per_usd(self) -> float | None:
        return None


class CostBasis(StrEnum):
    PER_TOKEN = "per_token"
    AMORTISED = "amortised"


class TokenCost(BaseModel):
    """The two costs, both resident in the registry (BRIEF v2 §3).

    `marginal_*` drives ROUTING. `allocated_*` drives REPORTING. They are equal
    for per-token placements and diverge sharply for `local`, where marginal cost
    approaches energy-only while capacity is free and converges on the spill
    price as the queue fills.

    Never substitute one for the other. Routing on allocated cost makes an idle
    GPU look expensive so you never use hardware you already bought; reporting on
    marginal cost books savings you did not make.
    """

    model_config = ConfigDict(extra="forbid")

    basis: CostBasis
    marginal_input_usd_per_mtok: float
    marginal_output_usd_per_mtok: float
    allocated_input_usd_per_mtok: float
    allocated_output_usd_per_mtok: float
    computed_at: datetime | None = None
    # Populated for amortised placements so the number can be audited.
    derivation: dict[str, float] | None = None


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: HealthState = HealthState.UNKNOWN
    checked_at: datetime | None = None
    detail: str | None = None


class Fingerprint(BaseModel):
    """Behavioural fingerprint used to catch silent degradation (PLAN.md Q5)."""

    model_config = ConfigDict(extra="forbid")

    provider_fingerprint: str | None = None
    behavioural_hash: str | None = None
    checked_at: datetime | None = None


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    lab: str = "unknown"

    # (model, effort) is the ROUTABLE UNIT, not model (BRIEF §3, cost data).
    # `family` groups the effort variants of one underlying model so the
    # escalator can walk the dial before switching families.
    family: str = ""
    # `effort` is the PROVIDER'S OWN LABEL -- "max", "high", "xhigh", "default".
    # Routing logic must never compare these strings: the vocabulary is vendor
    # semantics and the ordering is not universal (is "xhigh" above or below
    # "max"? it depends whose model it is). Ordering comes from `effort_rank`,
    # supplied by config. See FINDINGS.md F007.
    effort: str = "default"
    effort_rank: int = 0
    access: Access = Access.UNKNOWN
    placement: Placement = Placement.UNKNOWN
    lifecycle: Lifecycle = Lifecycle.CANDIDATE

    verified: bool = False
    verified_at: datetime | None = None

    scores: Scores = Field(default_factory=Scores)
    benchmark: Benchmark = Field(default_factory=Benchmark)
    context_window: int | None = None
    modalities: list[str] = Field(default_factory=list)
    pricing: Pricing | None = None
    # Derived at load/refresh time. Routing reads cost.marginal_*; reporting
    # reads cost.allocated_*. See FINDINGS.md F002 and PLAN.md §5.4.
    cost: TokenCost | None = None

    provider: str | None = None
    provider_model_id: str | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)
    api_features: list[Literal["tools", "json_schema", "json_object"]] = Field(default_factory=list)

    fingerprint: Fingerprint = Field(default_factory=Fingerprint)
    health: Health = Field(default_factory=Health)
    notes: str | None = None

    def selectable_reasons(self) -> list[str]:
        """Why this entry may NOT be selected. Empty list == selectable.

        Kept as reasons rather than a bare bool because `explain: true` has to
        show an operator why a model was excluded (PLAN.md §5.1).
        """
        reasons: list[str] = []
        if not self.verified:
            reasons.append("unverified")
        if self.lifecycle in (Lifecycle.DEPRECATED, Lifecycle.QUARANTINED):
            reasons.append(f"lifecycle:{self.lifecycle}")
        if self.lifecycle == Lifecycle.CANDIDATE:
            reasons.append("lifecycle:candidate")
        if self.placement == Placement.UNKNOWN:
            reasons.append("placement_unknown")
        if self.placement != Placement.LOCAL and self.pricing is None:
            reasons.append("no_pricing")
        if self.cost is None:
            reasons.append("no_cost_model")
        if self.health.state == HealthState.DOWN:
            reasons.append("health_down")
        if self.benchmark.cost_status == CostStatus.UNKNOWN and self.cost is None:
            # Benchmark averages are not billing prices. Verified token rates
            # suffice even when no benchmark cost has been published.
            reasons.append("cost_unknown")
        return reasons

    @property
    def routable_unit(self) -> tuple[str, str]:
        """The unit the router actually selects: (family, effort)."""
        return (self.family or self.id, self.effort)

    @property
    def is_selectable(self) -> bool:
        return not self.selectable_reasons()
