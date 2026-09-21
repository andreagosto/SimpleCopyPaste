"""Desktop integration: icons, launcher entry and the extension payload."""

from __future__ import annotations

import json

from simpleclips import install


def test_bundled_icons_exist():
    source = install._icon_source()
    assert (source / "simpleclips.png").exists()      # artwork, app icon
    assert (source / install.PANEL_ICON_SOURCE).exists()  # glyph, panel icon


def test_copy_panel_icon_into_extension(tmp_path):
    install._copy_icon_into(tmp_path)
    # named as the extension expects it, whatever the source file is called
    assert (tmp_path / install.PANEL_ICON_NAME).exists()


def test_install_icons_writes_every_size(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_icons_dir", lambda: tmp_path / "hicolor")
    assert install.install_icons() is True
    for size in install.ICON_SIZES:
        path = tmp_path / "hicolor" / f"{size}x{size}" / "apps" / "simpleclips.png"
        assert path.exists(), f"missing {size}px icon"


def test_install_desktop_points_at_the_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_applications_dir", lambda: tmp_path / "applications")
    path = install.install_desktop()
    text = path.read_text(encoding="utf-8")
    assert "Name=SimpleClips" in text
    assert "Icon=simpleclips" in text
    # GNOME pairs the running window with this entry through the WM class
    assert "StartupWMClass=Simpleclips" in text
    exec_line = next(l for l in text.splitlines() if l.startswith("Exec="))
    assert exec_line.endswith(" settings")


def test_remove_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_applications_dir", lambda: tmp_path / "applications")
    install.install_desktop()
    install.remove_desktop()
    assert not (tmp_path / "applications" / install.DESKTOP_NAME).exists()


def test_extension_metadata_is_valid_and_current():
    metadata = json.loads(
        (install._extension_source() / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["uuid"] == install.EXTENSION_UUID
    assert metadata["version"] >= 4
    assert "shell-version" in metadata
