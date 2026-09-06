from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from router_core.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return ROOT / "config"


@pytest.fixture()
def config(config_dir):
    return load_config(config_dir, env="dev")


@pytest.fixture()
def client(config_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from router_core.gateway.app import create_app

    monkeypatch.setenv("ROUTER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("ROUTER_ENV", "dev")
    with TestClient(create_app()) as c:
        yield c
