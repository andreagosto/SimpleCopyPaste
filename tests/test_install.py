"""Desktop integration: icons and the GNOME extension payload."""

from __future__ import annotations

import json
from pathlib import Path

from simpleclips import install


def test_extension_extras_cover_both_icon_formats():
    assert "simpleclips.svg" in install.EXTENSION_EXTRAS
    assert "simpleclips.png" in install.EXTENSION_EXTRAS


def test_bundled_icons_exist():
    source = install._icon_source()
    for name in install.EXTENSION_EXTRAS:
        assert (source / name).exists(), f"missing bundled icon {name}"


def test_copy_icon_into_extension(tmp_path):
    install._copy_icon_into(tmp_path)
    for name in install.EXTENSION_EXTRAS:
        assert (tmp_path / name).exists()


def test_install_icons_places_svg_and_png(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_icons_dir", lambda: tmp_path / "hicolor")
    assert install.install_icons() is True
    assert (tmp_path / "hicolor" / "scalable" / "apps" / "simpleclips.svg").exists()
    assert (tmp_path / "hicolor" / "512x512" / "apps" / "simpleclips.png").exists()


def test_extension_metadata_is_valid_and_current():
    metadata = json.loads(
        (install._extension_source() / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["uuid"] == install.EXTENSION_UUID
    assert metadata["version"] >= 3
    assert "shell-version" in metadata
