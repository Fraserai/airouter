"""The business case, reproduced from the seed data as a sanity baseline.

BRIEF §3: "Fable 5.1 costs roughly 61x what Luna costs for about 33% more index.
The whole business case is in that ratio."

This is a SANITY CHECK on the seed numbers, not a claim about the router. It is
the ceiling of the opportunity, not the expected result -- see FINDINGS.md F009.
"""

from __future__ import annotations

from router_core.registry.store import load_registry


def test_frontier_to_cheap_closed_cost_ratio_is_roughly_61x(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    top = registry.get("fable-5-1@frontier:max")
    cheap = registry.get("gpt-5-6-luna@frontier:max")

    cost_ratio = top.benchmark.cost_per_task_usd / cheap.benchmark.cost_per_task_usd
    index_ratio = top.scores.composite / cheap.scores.composite

    assert 55 <= cost_ratio <= 65, f"expected ~61x, got {cost_ratio:.1f}x"
    assert 1.30 <= index_ratio <= 1.36, f"expected ~1.33x, got {index_ratio:.2f}x"


def test_both_ends_of_that_ratio_are_closed_models(config_dir):
    """The headline spread is not an open-vs-closed story. Both are closed."""
    registry = load_registry(config_dir / "models.seed.yaml")
    assert registry.get("fable-5-1@frontier:max").access.value == "closed"
    assert registry.get("gpt-5-6-luna@frontier:max").access.value == "closed"


def test_neither_end_of_the_ratio_is_routable_yet(config_dir):
    """Unverified means unroutable, including the models in the business case."""
    registry = load_registry(config_dir / "models.seed.yaml")
    assert not registry.get("fable-5-1@frontier:max").is_selectable
    assert not registry.get("gpt-5-6-luna@frontier:max").is_selectable
