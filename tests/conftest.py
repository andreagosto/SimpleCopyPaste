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


def _display_available() -> bool:
    """Whether GTK can open a display, checked without aborting the process."""
    try:
        from simplecopypaste.gtk_ui import Gtk

        # init_check returns (ok, argv): a tuple, and therefore always truthy.
        # Read the first element rather than the object.
        result = Gtk.init_check()
    except Exception:
        return False
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


DISPLAY_AVAILABLE = _display_available()


@pytest.fixture
def gui():
    """Skip a test that builds real GTK windows when there is no display.

    The rest of the suite runs headless; only the few tests that need to
    watch focus or click-away behaviour need a display at all.
    """
    if not DISPLAY_AVAILABLE:
        pytest.skip("no display available")
    return True
