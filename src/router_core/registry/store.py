"""Registry loading and lookup.

The registry is content-addressed: `version` is a hash of the normalised entry
set. Every ledger row records it, which is what makes "replay a request to the
same routing decision" (BRIEF §10.8) achievable rather than aspirational --
a decision is only reproducible if you know what the candidate pool looked like
at the time.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml

from router_core.registry.schema import EVAL_KEYS, Lifecycle, ModelEntry, Placement


class RegistryError(RuntimeError):
    pass


class Registry:
    """An immutable snapshot of the model catalogue."""

    def __init__(self, entries: Iterable[ModelEntry], source: dict[str, Any] | None = None):
        self._entries: dict[str, ModelEntry] = {}
        for e in entries:
            if e.id in self._entries:
                raise RegistryError(f"duplicate registry id: {e.id}")
            self._entries[e.id] = e
        self.source = source or {}
        self.version = self._compute_version()

    def _compute_version(self) -> str:
        payload = json.dumps(
            [
                self._entries[k].model_dump(mode="json", exclude={"cost": {"computed_at"}})
                for k in sorted(self._entries)
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        return "reg_" + hashlib.sha256(payload.encode()).hexdigest()[:16]

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[ModelEntry]:
        return iter(self._entries.values())

    def __contains__(self, model_id: object) -> bool:
        return model_id in self._entries

    def get(self, model_id: str) -> ModelEntry:
        try:
            return self._entries[model_id]
        except KeyError:
            raise RegistryError(f"unknown model id: {model_id}") from None

    def all(self) -> list[ModelEntry]:
        return list(self._entries.values())

    def selectable(self) -> list[ModelEntry]:
        """The candidate pool. Empty until models are verified -- by design."""
        return [e for e in self._entries.values() if e.is_selectable]

    def ranked(self) -> list[ModelEntry]:
        """Catalog ranking: intelligence first, benchmark cost breaks ties.

        This ranks the supplied market snapshot; it does not price a request
        or certify a deployment. Unknown scores sort after measured scores.
        """
        return sorted(
            self.all(),
            key=lambda entry: (
                -(entry.scores.composite if entry.scores.composite is not None else -1),
                entry.benchmark.cost_per_task_usd
                if entry.benchmark.cost_per_task_usd is not None
                else float("inf"),
                entry.id,
            ),
        )

    def by_placement(self, placement: Placement) -> list[ModelEntry]:
        return [e for e in self._entries.values() if e.placement == placement]

    def by_lifecycle(self, lifecycle: Lifecycle) -> list[ModelEntry]:
        return [e for e in self._entries.values() if e.lifecycle == lifecycle]

    def family(self, family: str, placement: Placement | None = None) -> list[ModelEntry]:
        """Every effort variant of one model, ordered cheapest-effort first.

        Ordered by `effort_rank`, never by the effort label -- the labels are
        vendor vocabulary ("max", "xhigh", "high") with no universal ordering.
        See FINDINGS.md F007.
        """
        entries = [e for e in self._entries.values() if e.family == family]
        if placement is not None:
            entries = [e for e in entries if e.placement == placement]
        return sorted(entries, key=lambda e: e.effort_rank)

    def effort_siblings(self, entry: ModelEntry) -> list[ModelEntry]:
        return self.family(entry.family, entry.placement)

    def next_effort_up(self, entry: ModelEntry) -> ModelEntry | None:
        """The cheapest escalation move: same model, one notch more effort.

        The escalator tries this before switching families, because turning the
        dial is cheaper than changing model -- but only when the failure looks
        like under-thinking. See FINDINGS.md F008.
        """
        for sibling in self.effort_siblings(entry):
            if sibling.effort_rank > entry.effort_rank:
                return sibling
        return None

    def routers(self) -> list[ModelEntry]:
        return self.by_lifecycle(Lifecycle.ROUTER)

    def with_entry(self, entry: ModelEntry) -> Registry:
        """Return a new Registry with `entry` added or replaced. Snapshots are
        immutable so a version always identifies exactly one candidate pool."""
        merged = dict(self._entries)
        merged[entry.id] = entry
        return Registry(merged.values(), self.source)

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "total": len(self),
            "selectable": len(self.selectable()),
            "by_placement": {
                p.value: len(self.by_placement(p)) for p in Placement if self.by_placement(p)
            },
            "by_lifecycle": {
                lc.value: len(self.by_lifecycle(lc)) for lc in Lifecycle if self.by_lifecycle(lc)
            },
        }


def _coerce_entry(raw: dict[str, Any], source: dict[str, Any]) -> ModelEntry:
    data = dict(raw)
    scores = dict(data.get("scores") or {})
    # The seed file supplies only the composite. Fill the ten sub-eval keys with
    # None so the schema shape is stable from day one (BRIEF §3 rule 3).
    for key in EVAL_KEYS:
        scores.setdefault(key, None)
    scores.setdefault("source", f"{source.get('name')} {source.get('version')}".strip())
    scores.setdefault("measured_at", source.get("snapshot_date"))
    data["scores"] = scores
    return ModelEntry.model_validate(data)


def load_registry(path: str | Path = "config/models.seed.yaml") -> Registry:
    path = Path(path)
    if not path.exists():
        raise RegistryError(f"registry file not found: {path}")
    doc = yaml.safe_load(path.read_text()) or {}
    source = doc.get("source") or {}
    raw_models = doc.get("models") or []
    if not raw_models:
        raise RegistryError(f"registry file has no models: {path}")
    return Registry((_coerce_entry(m, source) for m in raw_models), source)
