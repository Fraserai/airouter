"""Amortised cost model for `local` placement.

Local cost is not per-token, and it is not one number. See BRIEF v2 §3 and
PLAN.md §5.4.

  allocated -- amortised capex + power + ops over ACHIEVED throughput.
               Used for reporting, mix accounting and the savings arithmetic.
               Answers "what did this fleet cost us per token last window."

  marginal  -- energy per token, plus a congestion term. Used for routing.
               Answers "what does it cost to admit ONE more request right now."
               While the box is idle this is near zero: the capex is sunk whether
               we route to it or not. As the queue fills, the real cost of
               admitting another request converges on the price of the model we
               would have to spill to.

Throughput is MEASURED, never assumed. With no measurement we refuse to produce
a cost rather than inventing one, which keeps the model unroutable -- the same
discipline as refusing to guess a vendor price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from router_core.registry.schema import CostBasis, TokenCost

HOURS_PER_MONTH = 730.0
_MTOK = 1_000_000.0


@dataclass(frozen=True)
class LocalTelemetry:
    """Live measurements from a local serving backend."""

    measured_tokens_per_hour: float
    queue_depth: int = 0
    queue_capacity: int = 1
    # Price of the placement we would spill to if we cannot serve in time.
    spill_output_usd_per_mtok: float = 0.0
    spill_input_usd_per_mtok: float = 0.0


def congestion_probability(queue_depth: int, queue_capacity: int, exponent: float = 2.0) -> float:
    """P(SLO breach | queue state).

    PLACEHOLDER MODEL. A convex function of utilisation with a tunable exponent,
    standing in for a real queueing model fitted to measured wait times. It has
    the right shape -- near zero while there is headroom, rising sharply as the
    queue saturates -- but the curve is not calibrated. Flagged in FINDINGS.md;
    replace once we have latency histograms from a real fleet.
    """
    if queue_capacity <= 0:
        return 1.0
    utilisation = min(max(queue_depth / queue_capacity, 0.0), 1.0)
    return utilisation**exponent


def derive_local_cost(
    hardware: dict[str, float],
    telemetry: LocalTelemetry,
    congestion_exponent: float = 2.0,
) -> TokenCost | None:
    """Return both cost numbers for a local deployment, or None if unmeasurable."""
    tph = telemetry.measured_tokens_per_hour
    if not tph or tph <= 0:
        # No measured throughput -> no honest cost -> not routable.
        return None

    capex = float(hardware.get("capex_usd", 0.0))
    months = float(hardware.get("amortisation_months", 36) or 36)
    power_kw = float(hardware.get("power_kw", 0.0))
    usd_per_kwh = float(hardware.get("power_usd_per_kwh", 0.0))
    ops_month = float(hardware.get("ops_usd_per_month", 0.0))

    capex_hourly = (capex / months / HOURS_PER_MONTH) if months else 0.0
    power_hourly = power_kw * usd_per_kwh
    ops_hourly = ops_month / HOURS_PER_MONTH

    allocated_hourly = capex_hourly + power_hourly + ops_hourly
    allocated_per_mtok = (allocated_hourly / tph) * _MTOK

    # Marginal: energy only, plus the opportunity cost of congestion.
    energy_per_mtok = (power_hourly / tph) * _MTOK
    p_breach = congestion_probability(
        telemetry.queue_depth, telemetry.queue_capacity, congestion_exponent
    )
    marginal_in = energy_per_mtok + p_breach * telemetry.spill_input_usd_per_mtok
    marginal_out = energy_per_mtok + p_breach * telemetry.spill_output_usd_per_mtok

    return TokenCost(
        basis=CostBasis.AMORTISED,
        marginal_input_usd_per_mtok=marginal_in,
        marginal_output_usd_per_mtok=marginal_out,
        allocated_input_usd_per_mtok=allocated_per_mtok,
        allocated_output_usd_per_mtok=allocated_per_mtok,
        computed_at=datetime.now(UTC),
        derivation={
            "capex_hourly_usd": capex_hourly,
            "power_hourly_usd": power_hourly,
            "ops_hourly_usd": ops_hourly,
            "measured_tokens_per_hour": tph,
            "congestion_probability": p_breach,
            "energy_usd_per_mtok": energy_per_mtok,
        },
    )
