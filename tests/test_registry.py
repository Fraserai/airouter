"""The registry's job on day one is to refuse to route. These tests hold it to that."""

from __future__ import annotations

from router_core.registry.schema import Lifecycle, ModelEntry, Placement
from router_core.registry.store import RegistryError, load_registry


def test_seed_registry_loads_all_23_models(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    assert len(registry) == 23


def test_no_seed_model_is_selectable(config_dir):
    """BRIEF §3 rule 2. Unverified means unroutable -- a compliance requirement."""
    registry = load_registry(config_dir / "models.seed.yaml")
    assert registry.selectable() == []


def test_every_seed_model_is_unverified_and_unpriced(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    for entry in registry:
        assert entry.verified is False, entry.id
        assert entry.pricing is None, f"{entry.id} has a guessed price"


def test_subscore_schema_exists_even_though_seed_supplies_only_composite(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    entry = registry.get("fable-5-1@frontier:max")
    assert entry.scores.composite == 53
    assert entry.scores.has_subscores is False
    assert entry.scores.terminal_bench_v2_1 is None  # present in schema, unset


def test_registry_version_is_content_addressed(config_dir):
    a = load_registry(config_dir / "models.seed.yaml")
    b = load_registry(config_dir / "models.seed.yaml")
    assert a.version == b.version

    changed = a.with_entry(a.get("kimi-k3@cloud:max").model_copy(update={"verified": True}))
    assert changed.version != a.version, "registry version must change when the pool does"


def test_selectable_reasons_are_explanatory_not_boolean(config_dir):
    registry = load_registry(config_dir / "models.seed.yaml")
    reasons = registry.get("inkling@unknown:default").selectable_reasons()
    assert "unverified" in reasons
    assert "placement_unknown" in reasons


def test_duplicate_ids_are_rejected():
    a = ModelEntry(id="dupe", display_name="A")
    b = ModelEntry(id="dupe", display_name="B")
    try:
        from router_core.registry.store import Registry

        Registry([a, b])
    except RegistryError:
        return
    raise AssertionError("duplicate registry ids must be rejected")


def test_placement_open_classification():
    assert Placement.LOCAL.is_open
    assert Placement.CLOUD_OPEN.is_open
    assert not Placement.CLOSED_FRONTIER.is_open


def test_quarantined_lifecycle_exists_and_blocks_selection():
    """Silent degradation is a suspicion, not a decision (FINDINGS.md F003/Q5)."""
    entry = ModelEntry(id="x@y", display_name="X", lifecycle=Lifecycle.QUARANTINED)
    assert "lifecycle:quarantined" in entry.selectable_reasons()
