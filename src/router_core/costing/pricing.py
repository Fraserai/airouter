"""Cost derivation for every placement.

For per-token placements the two numbers coincide: the marginal cost of one more
token IS the price. For `local` they diverge and come from local_amortised.
"""

from __future__ import annotations

from datetime import UTC, datetime

from router_core.costing.local_amortised import LocalTelemetry, derive_local_cost
from router_core.registry.schema import CostBasis, ModelEntry, Placement, TokenCost


def derive_per_token_cost(entry: ModelEntry) -> TokenCost | None:
    """Marginal == allocated for metered APIs. None if unpriced (never guessed)."""
    if entry.pricing is None:
        return None
    p = entry.pricing
    return TokenCost(
        basis=CostBasis.PER_TOKEN,
        marginal_input_usd_per_mtok=p.input_usd_per_mtok,
        marginal_output_usd_per_mtok=p.output_usd_per_mtok,
        allocated_input_usd_per_mtok=p.input_usd_per_mtok,
        allocated_output_usd_per_mtok=p.output_usd_per_mtok,
        computed_at=datetime.now(UTC),
    )


def derive_cost(
    entry: ModelEntry,
    *,
    hardware: dict[str, float] | None = None,
    telemetry: LocalTelemetry | None = None,
    congestion_exponent: float = 2.0,
) -> TokenCost | None:
    if entry.placement == Placement.LOCAL:
        if hardware is None or telemetry is None:
            return None
        return derive_local_cost(hardware, telemetry, congestion_exponent)
    return derive_per_token_cost(entry)


def estimate_usd(
    cost: TokenCost, input_tokens: int, output_tokens: int, *, marginal: bool
) -> float:
    """Cost of a request. `marginal=True` for routing decisions, False for reporting.

    The caller must state which one it wants. There is no default, deliberately:
    picking the wrong one is the single easiest way to break this product, and a
    default would let it happen silently.
    """
    if marginal:
        rate_in = cost.marginal_input_usd_per_mtok
        rate_out = cost.marginal_output_usd_per_mtok
    else:
        rate_in = cost.allocated_input_usd_per_mtok
        rate_out = cost.allocated_output_usd_per_mtok
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000.0
