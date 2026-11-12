"""Configuration loading.

Everything the router behaves on comes from here. No vendor name, model name or
price appears anywhere outside `config/` (BRIEF §13), enforced by
`scripts/lint_no_vendor.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from router_core.costing.pricing import derive_cost
from router_core.registry.schema import ModelEntry
from router_core.registry.store import Registry, load_registry

DEFAULT_CONFIG_DIR = Path("config")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    return yaml.safe_load(path.read_text()) or {}


@dataclass(frozen=True)
class AppConfig:
    env: str
    config_dir: Path
    router: dict[str, Any]
    quality_floors: dict[str, Any]
    placements: dict[str, Any]
    registry: Registry
    catalog: Registry

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def intelligence_model(self) -> str | None:
        configured = (self.router.get("router") or {}).get("intelligence_model", "auto")
        if configured != "auto":
            return configured
        ranked = self.catalog.ranked()
        return ranked[0].id if ranked else None


def _attach_costs(registry: Registry, placements: dict[str, Any]) -> Registry:
    """Derive the two cost numbers for every entry that can honestly have them.

    An entry with no derivable cost keeps `cost=None` and is therefore not
    selectable. We never fabricate a number to make the pool look healthier.
    """
    placement_cfg = placements.get("placements") or {}
    out = registry
    for entry in registry.all():
        hardware = None
        telemetry = None
        if entry.placement.value == "local":
            hardware = (placement_cfg.get("local") or {}).get("hardware")
            # Throughput is MEASURED. Until a local backend reports it there is
            # no honest local cost, so local models stay unroutable.
            telemetry = None
        cost = derive_cost(entry, hardware=hardware, telemetry=telemetry)
        if cost is not None:
            out = out.with_entry(entry.model_copy(update={"cost": cost}))
    return out


def _attach_catalog_endpoints(registry: Registry, config_dir: Path) -> Registry:
    """Attach mapped hosted endpoints without certifying a deployment.

    The chart map is a connection hint only. Entries retain their unverified
    state and therefore remain ineligible until the provider evidence gate is
    completed. Local and unknown placements are left untouched because a hosted
    endpoint would change the product's placement semantics.
    """
    mapping_path = config_dir / "chart-provider-map.yaml"
    if not mapping_path.exists():
        return registry
    mapping = _read_yaml(mapping_path).get("models") or {}
    out = registry
    for entry in registry.all():
        endpoint = mapping.get(entry.id)
        if (
            endpoint
            and entry.provider is None
            and entry.placement.value not in {"local", "unknown"}
        ):
            out = out.with_entry(
                entry.model_copy(update={"provider": "openrouter", "provider_model_id": endpoint})
            )
    return out


def load_config(config_dir: str | Path | None = None, env: str | None = None) -> AppConfig:
    config_dir = Path(config_dir or os.environ.get("ROUTER_CONFIG_DIR", DEFAULT_CONFIG_DIR))
    env = env or os.environ.get("ROUTER_ENV", "dev")
    if env not in {"dev", "live", "production"}:
        raise ValueError("ROUTER_ENV must be dev, live, or production")

    catalog = load_registry(config_dir / "models.seed.yaml")
    registry = catalog

    live_overlay = config_dir / "models.live.yaml"
    if env in {"live", "production"} and live_overlay.exists():
        for entry in load_registry(live_overlay).all():
            registry = registry.with_entry(entry)

    # Dev overlay carries the deterministic stub. Never loaded in production.
    dev_overlay = config_dir / "models.dev.yaml"
    if env != "production" and dev_overlay.exists():
        overlay = load_registry(dev_overlay)
        for entry in overlay.all():
            registry = registry.with_entry(entry)

    registry = _attach_catalog_endpoints(registry, config_dir)

    placements = _read_yaml(config_dir / "placements.yaml")
    registry = _attach_costs(registry, placements)

    return AppConfig(
        env=env,
        config_dir=config_dir,
        router=_read_yaml(config_dir / "router.yaml"),
        quality_floors=_read_yaml(config_dir / "quality_floors.yaml"),
        placements=placements,
        registry=registry,
        catalog=catalog,
    )


def selectable_summary(registry: Registry) -> dict[str, Any]:
    """Why the pool looks the way it does -- the first thing an operator asks."""
    blocked: dict[str, int] = {}
    for entry in registry.all():
        for reason in entry.selectable_reasons():
            blocked[reason] = blocked.get(reason, 0) + 1
    return {**registry.summary(), "blocked_by": blocked}


__all__ = ["AppConfig", "ModelEntry", "load_config", "selectable_summary"]
