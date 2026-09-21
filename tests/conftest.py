"""Shared fixtures: isolate XDG dirs so tests never touch the real history."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    data = tmp_path / "data"
    config = tmp_path / "config"
    runtime = tmp_path / "run"
    for path in (data, config, runtime):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    yield
