"""Check the supplied benchmark comparisons; these are not live savings."""

import pytest

from router_core.registry.store import load_registry


@pytest.mark.parametrize(
    "expensive_id,cheap_id,ratio,savings",
    [
        ("gpt-5-6-terra@frontier:max", "glm-5-3-flash@cloud:default", 5.6, 0.8214285714),
        ("fable-5-1@frontier:max", "gpt-6-astra@frontier:max", 7.63 / 3.26, 0.5727391874),
    ],
)
def test_supplied_equal_index_comparisons(config_dir, expensive_id, cheap_id, ratio, savings):
    registry = load_registry(config_dir / "models.seed.yaml")
    expensive, cheap = registry.get(expensive_id), registry.get(cheap_id)
    assert expensive.scores.composite == cheap.scores.composite
    assert (
        expensive.benchmark.cost_per_task_usd / cheap.benchmark.cost_per_task_usd
        == pytest.approx(ratio)
    )
    assert (
        1 - cheap.benchmark.cost_per_task_usd / expensive.benchmark.cost_per_task_usd
        == pytest.approx(savings)
    )
    assert not expensive.is_selectable and not cheap.is_selectable
