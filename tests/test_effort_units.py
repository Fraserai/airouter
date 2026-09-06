"""(model, effort) is the routable unit, and effort ordering comes from config."""

from __future__ import annotations

from router_core.registry.schema import ModelEntry, Placement
from router_core.registry.store import Registry, load_registry

_SHORT = {Placement.CLOUD_OPEN: "cloud", Placement.LOCAL: "local"}


def _family(placement=Placement.CLOUD_OPEN) -> Registry:
    return Registry(
        [
            ModelEntry(
                id=f"m@{_SHORT[placement]}:{effort}",
                display_name=f"M ({effort})",
                family="m",
                effort=effort,
                effort_rank=rank,
                placement=placement,
            )
            # Deliberately out of rank order, and deliberately using labels whose
            # alphabetical order disagrees with their effort order.
            for effort, rank in (("max", 3), ("default", 0), ("high", 2))
        ]
    )


def test_routable_unit_is_family_and_effort(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    entry = registry.get("qwen-3-8-27b@local:xhigh")
    assert entry.routable_unit == ("qwen-3-8-27b", "xhigh")
    assert entry.family == "qwen-3-8-27b"


def test_effort_variants_order_by_rank_not_label():
    """Alphabetically 'default' < 'high' < 'max'. That is a coincidence here and
    is not true in general -- 'xhigh' sorts after 'max' but is not universally
    more effort. Ordering must come from the config-supplied rank."""
    registry = _family()
    ordered = [e.effort for e in registry.family("m")]
    assert ordered == ["default", "high", "max"]
    assert [e.effort_rank for e in registry.family("m")] == [0, 2, 3]


def test_next_effort_up_is_the_cheapest_escalation_move():
    registry = _family()
    low = registry.get("m@cloud:default")
    assert registry.next_effort_up(low).effort == "high"
    assert registry.next_effort_up(registry.get("m@cloud:high")).effort == "max"
    assert registry.next_effort_up(registry.get("m@cloud:max")) is None


def test_effort_siblings_do_not_cross_placement():
    """Turning the dial must not silently move data across the perimeter."""
    entries = list(_family(Placement.LOCAL)) + [
        ModelEntry(
            id="m@cloud:max",
            display_name="M cloud",
            family="m",
            effort="max",
            effort_rank=3,
            placement=Placement.CLOUD_OPEN,
        )
    ]
    registry = Registry(entries)
    local_max = registry.get("m@local:max")
    assert registry.next_effort_up(local_max) is None
    assert all(e.placement == local_max.placement for e in registry.effort_siblings(local_max))
