#!/usr/bin/env python
"""Fail loudly on unverified registry entries (BRIEF §3 rule 2).

A router that silently misclassifies a closed model as open is a compliance
incident, not a bug. This script is the gate. It exits non-zero whenever any
entry is enabled-looking but unverified, and it prints exactly what is missing.

Expected result on a fresh checkout: FAILURE, with 22 unverified entries. That
is the system working.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router_core.config import load_config  # noqa: E402
from router_core.registry.schema import Access, CostStatus, Placement  # noqa: E402

REQUIRED_WHEN_VERIFIED = ("context_window", "modalities", "provider", "provider_model_id")


def audit(entry) -> list[str]:
    problems: list[str] = []
    if not entry.verified:
        problems.append("verified=false")
    if entry.verified and entry.verified_at is None:
        problems.append("verified_at missing")
    if entry.access == Access.UNKNOWN:
        problems.append("access unknown (open/closed unconfirmed)")
    if entry.placement == Placement.UNKNOWN:
        problems.append("placement unknown")
    if entry.placement != Placement.LOCAL and entry.pricing is None:
        problems.append("pricing missing")
    if entry.cost is None:
        problems.append("no derivable cost model")
    if entry.benchmark.cost_status == CostStatus.UNKNOWN:
        problems.append("cost_unknown (no published cost; cannot be priced)")
    if not entry.family:
        problems.append("family missing (needed for the effort escalation ladder)")
    if entry.verified:
        for field in REQUIRED_WHEN_VERIFIED:
            value = getattr(entry, field, None)
            if value in (None, [], ""):
                problems.append(f"{field} missing")
    if not entry.scores.has_subscores:
        # Not fatal, but it means the entry can only serve task classes whose
        # floor is empty. See FINDINGS.md F004.
        problems.append("no sub-eval scores (capability-specific routing blocked)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--strict", action="store_true", help="also fail on soft warnings")
    args = parser.parse_args()

    config = load_config(args.config_dir)
    registry = config.registry

    hard_failures = 0
    print(f"registry_version: {registry.version}")
    print(f"entries: {len(registry)}  selectable: {len(registry.selectable())}\n")

    for entry in sorted(registry.all(), key=lambda e: e.id):
        problems = audit(entry)
        if not problems:
            print(f"  OK        {entry.id}")
            continue
        soft = [p for p in problems if p.startswith("no sub-eval")]
        hard = [p for p in problems if p not in soft]
        if hard:
            hard_failures += 1
            print(f"  UNVERIFIED {entry.id}")
            for p in hard:
                print(f"             - {p}")
            for p in soft:
                print(f"             ~ {p}")
        else:
            print(f"  WARN      {entry.id}")
            for p in soft:
                print(f"             ~ {p}")
            if args.strict:
                hard_failures += 1

    print()
    if hard_failures:
        print(
            f"FAIL: {hard_failures} entr{'y' if hard_failures == 1 else 'ies'} "
            "cannot be enabled for production routing."
        )
        print("Confirm open/closed status, licence, context window, modality support and")
        print("per-token pricing against the provider, then set verified/verified_at.")
        return 1
    print("PASS: every registry entry is verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
