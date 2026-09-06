"""verify_registry must fail loudly on a fresh checkout. That is the design."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_registry.py"


def test_fresh_checkout_fails_verification():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 1
    assert "FAIL" in result.stdout
    assert "cannot be enabled for production routing" in result.stdout


def test_failure_names_what_is_missing():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert "pricing missing" in result.stdout
    assert "verified=false" in result.stdout
