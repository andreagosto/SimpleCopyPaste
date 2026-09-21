"""Desktop integration: icons, launcher entry and the extension payload."""

from __future__ import annotations

import json

from simpleclips import install


def test_bundled_icons_exist():
    source = install._icon_source()
    assert (source / "simpleclips.png").exists()               # artwork, app icon
    assert (source / install.PANEL_ICON_SOURCE).exists()        # panel fallback
    assert (source / install.PANEL_ICON_SYMBOLIC).exists()      # panel symbolic


def test_panel_symbolic_name_carries_the_suffix():
    # GTK resolves "simpleclips-symbolic" by looking for a file of that name,
    # so the suffix has to be part of it.
    assert install.PANEL_ICON_NAME_SYMBOLIC.endswith("-symbolic")


def test_panel_symbolic_is_wellformed_and_starts_with_svg(tmp_path):
    # gdk-pixbuf sniffs the first bytes to pick a loader: anything before
    # "<svg" pushes the match out of its window and the icon fails to load.
    path = install._icon_source() / install.PANEL_ICON_SYMBOLIC
    head = path.read_bytes()[:400]
    svg_at = head.find(b"<svg")
    assert svg_at != -1
    assert b"<!--" not in head[:svg_at], "a comment before <svg breaks loading"


def test_extension_ships_a_stylesheet():
    # The panel draws status icons too small for a mark to read; the
    # stylesheet turns ours up. GNOME only loads it from this exact filename.
    stylesheet = install._extension_source() / "stylesheet.css"
    assert stylesheet.exists()
    assert "icon-size" in stylesheet.read_text(encoding="utf-8")


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


def test_install_icons_writes_the_symbolic(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "_icons_dir", lambda: tmp_path / "hicolor")
    install.install_icons()
    symbolic = (
        tmp_path / "hicolor" / "symbolic" / "apps"
        / f"{install.PANEL_ICON_NAME_SYMBOLIC}.svg"
    )
    assert symbolic.exists()


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


def test_extension_install_is_non_destructive(tmp_path, monkeypatch):
    """Installing must not wipe the extension folder.

    While the extension is running the Shell keeps a handle on that directory;
    deleting it leaves the extension disabled and unable to reload, because
    Wayland cannot reload the Shell in place.
    """
    ext_dir = tmp_path / "extensions"
    monkeypatch.setattr(install, "_extensions_dir", lambda: ext_dir)
    monkeypatch.setattr(install, "is_gnome_session", lambda: True)
    monkeypatch.setattr(install, "_gnome_extensions_cli", lambda: None)
    monkeypatch.setattr(install.shutil, "which", lambda name: None)

    target = ext_dir / install.EXTENSION_UUID
    target.mkdir(parents=True)
    (target / "marker").write_text("keep me", encoding="utf-8")

    notes = []
    install.install_extension(notes)
    assert (target / "marker").exists(), "install wiped the folder"
    assert (target / "extension.js").exists()
    assert (target / install.PANEL_ICON_NAME).exists()


def test_obsolete_extension_files_are_removed(tmp_path, monkeypatch):
    ext_dir = tmp_path / "extensions"
    monkeypatch.setattr(install, "_extensions_dir", lambda: ext_dir)
    monkeypatch.setattr(install, "is_gnome_session", lambda: True)
    monkeypatch.setattr(install, "_gnome_extensions_cli", lambda: None)
    monkeypatch.setattr(install.shutil, "which", lambda name: None)

    target = ext_dir / install.EXTENSION_UUID
    target.mkdir(parents=True)
    for stale in install.OBSOLETE_EXTENSION_FILES:
        (target / stale).write_text("old", encoding="utf-8")

    install.install_extension([])
    for stale in install.OBSOLETE_EXTENSION_FILES:
        assert not (target / stale).exists()


def test_extension_metadata_is_valid_and_current():
    metadata = json.loads(
        (install._extension_source() / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["uuid"] == install.EXTENSION_UUID
    assert metadata["version"] >= 10
    assert "shell-version" in metadata
