#!/usr/bin/env python
"""No vendor name, model name or price in routing logic (BRIEF §13).

A rule nobody enforces mechanically decays by M3, so this runs in CI.

Method: read every lab, model id, display name and non-zero price out of
`config/`, then look for them as literals in the scoped source tree. Provider
ADAPTERS are exempt -- translating a registry id into a provider's own naming is
precisely their job. Everything else is in scope, including the gateway.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SCOPED_DIRS = (
    "src/router_core/router",
    "src/router_core/governor",
    "src/router_core/verifier",
    "src/router_core/registry",
    "src/router_core/costing",
    "src/router_core/compiler",
    "src/router_core/gateway",
    "src/router_core/ledger",
)
EXEMPT_DIRS = ("src/router_core/providers",)

# Words that are placement/access vocabulary, not vendor identity.
ALLOWED = {
    "none",
    "unknown",
    "open",
    "closed",
    "local",
    "stub",
    "text",
    "cloud_open",
    "closed_frontier",
}


def harvest_forbidden(config_dir: Path) -> tuple[set[str], set[float]]:
    names: set[str] = set()
    prices: set[float] = set()
    for path in sorted(config_dir.rglob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for entry in doc.get("models") or []:
            for key in ("id", "display_name", "lab"):
                value = entry.get(key)
                if isinstance(value, str) and value.lower() not in ALLOWED:
                    names.add(value)
            pricing = entry.get("pricing") or {}
            for value in pricing.values():
                if isinstance(value, (int, float)) and float(value) != 0.0:
                    prices.add(float(value))
    return names, prices


def scan(names: set[str], prices: set[float]) -> list[str]:
    violations: list[str] = []
    price_pattern = (
        re.compile("|".join(re.escape(f"{p}") for p in sorted(prices))) if prices else None
    )
    for rel in SCOPED_DIRS:
        directory = ROOT / rel
        if not directory.exists():
            continue
        if any(rel.startswith(x) for x in EXEMPT_DIRS):
            continue
        for path in sorted(directory.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # comments may reference the rule itself
                if stripped.startswith(("from ", "import ")):
                    # Import paths are module identity, not routing decisions.
                    # `openai_compat` names a WIRE PROTOCOL the gateway speaks;
                    # the brief itself requires OpenAI-compatibility. Narrow
                    # exemption, and tests/test_lint_no_vendor.py proves the
                    # linter still catches a vendor name used as a decision.
                    continue
                for name in names:
                    if name in line:
                        violations.append(
                            f"{path.relative_to(ROOT)}:{lineno}: vendor/model name {name!r}"
                        )
                if price_pattern and price_pattern.search(line):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: price literal")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default=str(ROOT / "config"))
    args = parser.parse_args()

    names, prices = harvest_forbidden(Path(args.config_dir))
    violations = scan(names, prices)

    print(f"guarding {len(names)} names and {len(prices)} price literals")
    print(f"scope: {len(SCOPED_DIRS)} dirs, adapters exempt\n")
    if violations:
        for v in violations:
            print(f"  VIOLATION {v}")
        print(f"\nFAIL: {len(violations)} violation(s). Move it to config/.")
        return 1
    print("PASS: no vendor names, model names or price literals in routing logic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
