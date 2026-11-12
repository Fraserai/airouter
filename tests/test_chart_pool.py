"""The chart roster is mapped without confusing a catalog hit with access."""

from router_core.config import load_config
from router_core.providers.factory import build_adapters


def test_live_chart_models_have_endpoint_hints_and_keep_verification_gate(config_dir):
    config = load_config(config_dir, env="live")
    mapped = [
        entry
        for entry in config.registry.all()
        if entry.provider == "openrouter" and entry.provider_model_id
    ]
    # The hosted hints cover every non-local, classified chart entry whose
    # public endpoint matched. The local deployment and unknown-placement
    # entry stay unassigned until their placement/access evidence is settled.
    assert len(mapped) == 17
    assert all(not entry.is_selectable for entry in mapped)
    assert not any(entry.placement.value == "local" for entry in mapped)


def test_openrouter_adapter_covers_mapped_pool_without_enabling_it(config_dir, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    adapters = build_adapters(load_config(config_dir, env="live"))
    openrouter = next(adapter for adapter in adapters.adapters() if adapter.name == "openrouter")
    assert openrouter.configured is False
    assert openrouter.supports("fable-5-1@frontier:max")
    assert openrouter.supports("grok-4-6@frontier:high")
