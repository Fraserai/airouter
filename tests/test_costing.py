"""The two-number local cost model.

Getting this wrong breaks the product in one of two directions, so both
directions get a test.
"""

from __future__ import annotations

import pytest

from router_core.costing import LocalTelemetry, congestion_probability, derive_local_cost
from router_core.costing.pricing import derive_per_token_cost, estimate_usd
from router_core.registry.schema import CostBasis, ModelEntry, Placement, Pricing

HARDWARE = {
    "capex_usd": 120_000.0,
    "amortisation_months": 36,
    "power_kw": 6.0,
    "power_usd_per_kwh": 0.15,
    "ops_usd_per_month": 2_000.0,
}


def _telemetry(queue_depth: int) -> LocalTelemetry:
    return LocalTelemetry(
        measured_tokens_per_hour=3_000_000,
        queue_depth=queue_depth,
        queue_capacity=64,
        spill_output_usd_per_mtok=0.60,
        spill_input_usd_per_mtok=0.15,
    )


def test_idle_local_marginal_cost_is_far_below_allocated():
    """Route on allocated cost and an idle GPU looks expensive, so you never use
    hardware you already bought. This is the failure this test exists to catch."""
    cost = derive_local_cost(HARDWARE, _telemetry(queue_depth=0))
    assert cost is not None
    assert cost.marginal_output_usd_per_mtok < cost.allocated_output_usd_per_mtok / 5


def test_marginal_cost_rises_with_queue_depth_but_allocated_does_not():
    idle = derive_local_cost(HARDWARE, _telemetry(0))
    busy = derive_local_cost(HARDWARE, _telemetry(61))
    assert busy.marginal_output_usd_per_mtok > idle.marginal_output_usd_per_mtok
    assert busy.allocated_output_usd_per_mtok == pytest.approx(idle.allocated_output_usd_per_mtok)


def test_saturated_local_marginal_converges_on_spill_price():
    """At full queue the true cost of one more request is what spilling costs."""
    cost = derive_local_cost(HARDWARE, _telemetry(queue_depth=64))
    assert cost.marginal_output_usd_per_mtok >= 0.60


def test_unmeasured_throughput_yields_no_cost_rather_than_a_guess():
    cost = derive_local_cost(HARDWARE, LocalTelemetry(measured_tokens_per_hour=0))
    assert cost is None, "no measurement must mean no cost, never an invented one"


def test_congestion_probability_bounds():
    assert congestion_probability(0, 64) == 0.0
    assert congestion_probability(64, 64) == 1.0
    assert 0.0 < congestion_probability(32, 64) < 1.0


def test_per_token_placements_have_equal_marginal_and_allocated():
    entry = ModelEntry(
        id="m@cloud",
        display_name="M",
        placement=Placement.CLOUD_OPEN,
        pricing=Pricing(input_usd_per_mtok=0.5, output_usd_per_mtok=1.5),
    )
    cost = derive_per_token_cost(entry)
    assert cost.basis == CostBasis.PER_TOKEN
    assert cost.marginal_input_usd_per_mtok == cost.allocated_input_usd_per_mtok
    assert cost.marginal_output_usd_per_mtok == cost.allocated_output_usd_per_mtok


def test_unpriced_model_yields_no_cost():
    entry = ModelEntry(id="m@cloud", display_name="M", placement=Placement.CLOUD_OPEN)
    assert derive_per_token_cost(entry) is None


def test_estimate_usd_requires_explicit_marginal_choice():
    """No default. Picking the wrong number silently is the failure mode."""
    entry = ModelEntry(
        id="m@cloud",
        display_name="M",
        placement=Placement.CLOUD_OPEN,
        pricing=Pricing(input_usd_per_mtok=1.0, output_usd_per_mtok=2.0),
    )
    cost = derive_per_token_cost(entry)
    with pytest.raises(TypeError):
        estimate_usd(cost, 1000, 1000)  # type: ignore[call-arg]
    assert estimate_usd(cost, 1_000_000, 1_000_000, marginal=True) == pytest.approx(3.0)
