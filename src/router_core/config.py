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
    tenants: dict[str, dict[str, Any]]
    registry: Registry

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def intelligence_model(self) -> str | None:
        return (self.router.get("router") or {}).get("intelligence_model")

    @property
    def overhead_budget(self) -> dict[str, Any]:
        return self.router.get("overhead_budget") or {}

    def tenant(self, tenant_id: str) -> dict[str, Any]:
        return self.tenants.get(tenant_id) or self.tenants["default"]


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


def _load_tenants(config_dir: Path) -> dict[str, dict[str, Any]]:
    tenant_dir = config_dir / "tenants"
    tenants: dict[str, dict[str, Any]] = {}
    for path in sorted(tenant_dir.glob("*.yaml")):
        doc = _read_yaml(path)
        tenants[doc.get("tenant_id", path.stem)] = doc
    if "default" not in tenants:
        raise RuntimeError("config/tenants/default.yaml is required")
    return tenants


def load_config(config_dir: str | Path | None = None, env: str | None = None) -> AppConfig:
    config_dir = Path(config_dir or os.environ.get("ROUTER_CONFIG_DIR", DEFAULT_CONFIG_DIR))
    env = env or os.environ.get("ROUTER_ENV", "dev")

    registry = load_registry(config_dir / "models.seed.yaml")

    # Dev overlay carries the deterministic stub. Never loaded in production.
    dev_overlay = config_dir / "models.dev.yaml"
    if env != "production" and dev_overlay.exists():
        overlay = load_registry(dev_overlay)
        for entry in overlay.all():
            registry = registry.with_entry(entry)

    placements = _read_yaml(config_dir / "placements.yaml")
    registry = _attach_costs(registry, placements)

    return AppConfig(
        env=env,
        config_dir=config_dir,
        router=_read_yaml(config_dir / "router.yaml"),
        quality_floors=_read_yaml(config_dir / "quality_floors.yaml"),
        placements=placements,
        tenants=_load_tenants(config_dir),
        registry=registry,
    )


def selectable_summary(registry: Registry) -> dict[str, Any]:
    """Why the pool looks the way it does -- the first thing an operator asks."""
    blocked: dict[str, int] = {}
    for entry in registry.all():
        for reason in entry.selectable_reasons():
            blocked[reason] = blocked.get(reason, 0) + 1
    return {**registry.summary(), "blocked_by": blocked}


__all__ = ["AppConfig", "ModelEntry", "load_config", "selectable_summary"]
