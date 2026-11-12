"""Guards on what the SELECTION path is allowed to look at.

Two facts from the cost chart drive these:

  1. Cheap does not mean open. GPT-5.6 Luna is CLOSED, costs $0.18/benchmark task and
     scores 38 -- cheaper than most open models in this pool and stronger than
     several. The open/closed axis is governance and residency. It is not a cost
     proxy and selection must never treat it as one. There is no target share
     for open or closed execution.

  2. Benchmark cost-per-task is not a price. It is a weighted average over the
     index provider's task mix. Selection prices requests from TokenCost and the
     request's own token profile.

These are enforced by scanning source, because both mistakes are the kind that
look reasonable in a diff and are invisible at runtime until the bill arrives.
"""

from __future__ import annotations

from pathlib import Path

from router_core.registry.schema import Access, ModelEntry
from router_core.registry.store import load_registry

ROOT = Path(__file__).resolve().parents[1]

# Modules that decide WHICH MODEL SERVES A REQUEST.
SELECTION_DIRS = (ROOT / "src" / "router_core" / "router",)

FORBIDDEN_IN_SELECTION = (
    "is_open",  # open/closed is governance, never a selection signal
    "cost_per_task_usd",  # a benchmark average, never a price
    "index_per_usd",  # a browsing aid, never a routing rule
    "Access.OPEN",
    "Access.CLOSED",
)


def _selection_sources() -> list[Path]:
    return [p for d in SELECTION_DIRS if d.exists() for p in d.rglob("*.py")]


def test_selection_path_never_reads_openness_or_benchmark_cost():
    offenders = []
    for path in _selection_sources():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for token in FORBIDDEN_IN_SELECTION:
                if token in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {token}")
    assert not offenders, "selection must not read openness or benchmark cost:\n" + "\n".join(
        offenders
    )


def test_the_pool_really_does_contain_a_cheap_closed_model(config_dir):
    """The fact that motivates the rule above. If this ever stops being true the
    rule is still right, but the reviewer should know the example changed."""
    registry = load_registry(config_dir / "models.seed.yaml")
    closed = [
        e
        for e in registry
        if e.access == Access.CLOSED and e.benchmark.cost_per_task_usd is not None
    ]
    open_models = [
        e for e in registry if e.access == Access.OPEN and e.benchmark.cost_per_task_usd is not None
    ]
    cheapest_closed = min(closed, key=lambda e: e.benchmark.cost_per_task_usd)
    open_costs = sorted(e.benchmark.cost_per_task_usd for e in open_models)

    # The cheapest closed model undercuts the median open model.
    median_open = open_costs[len(open_costs) // 2]
    assert cheapest_closed.benchmark.cost_per_task_usd < median_open


def test_cost_unknown_entries_are_ineligible(config_dir):
    """A router that cannot price a model cannot choose it responsibly."""
    entry = ModelEntry(id="unpriced", display_name="Unpriced model")
    assert "cost_unknown" in entry.selectable_reasons()
    assert not entry.is_selectable
