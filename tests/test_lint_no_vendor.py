"""The vendor-name rule is enforced mechanically, and the enforcement works.

The linter exempts import lines (a wire-protocol module name is not a routing
decision). This test proves that exemption did not gut the rule.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lint_no_vendor.py"
GUARDED = ROOT / "src" / "router_core" / "router" / "_lint_probe.py"


def _run() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)


def test_clean_tree_passes():
    result = _run()
    assert result.returncode == 0, result.stdout


def test_planted_vendor_name_in_routing_logic_is_caught():
    GUARDED.write_text('LAB = "anthropic"\n')
    try:
        result = _run()
        assert result.returncode == 1
        assert "VIOLATION" in result.stdout
    finally:
        GUARDED.unlink(missing_ok=True)


def test_planted_model_id_in_routing_logic_is_caught():
    GUARDED.write_text('PREFERRED = "fable-5-1@frontier"\n')
    try:
        result = _run()
        assert result.returncode == 1
        assert "fable-5-1@frontier" in result.stdout
    finally:
        GUARDED.unlink(missing_ok=True)


def test_tree_is_clean_again_after_probes():
    assert not GUARDED.exists()
    assert _run().returncode == 0
