"""Desktop integration: systemd user service, GNOME keybinding, Shell extension."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_NAME
from . import hotkey

# The combo a fresh install binds, and the fallback when a stored one is
# missing or unusable.
DEFAULT_HOTKEY = "<Super><Alt>v"

SERVICE_NAME = "simplecopypaste.service"
EXTENSION_UUID = "simplecopypaste@simplecopypaste.github.io"
KEYBINDING_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/simplecopypaste/"
)
KEYBINDING_SCHEMA = (
    "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:" + KEYBINDING_PATH
)
MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"

SERVICE_TEMPLATE = """\
[Unit]
Description={app} clipboard history
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart={exec_path} daemon
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1
{env_extra}
[Install]
WantedBy=graphical-session.target
"""


def _service_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _exec_path() -> str:
    found = shutil.which("simplecopypaste")
    if found:
        return found
    return f"{sys.executable} -m simplecopypaste"


def _on_path() -> bool:
    return shutil.which("simplecopypaste") is not None


def _env_extra() -> str:
    """Running from a source checkout needs PYTHONPATH to find the package."""
    if _on_path():
        return ""
    src = Path(__file__).resolve().parents[1]
    return f"Environment=PYTHONPATH={src}"


def _run(argv: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run a helper command, tolerating one that is not installed.

    These helpers (gsettings, systemctl, update-desktop-database, ...) are
    all optional niceties: a missing one should degrade the integration, not
    crash the install. A missing binary is reported as exit code 127.
    """
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=check)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]}: not found")


def _gsettings_get(schema: str, key: str) -> str:
    proc = _run(["gsettings", "get", schema, key])
    return proc.stdout.strip()


def _gsettings_set(schema: str, key: str, value: str) -> bool:
    return _run(["gsettings", "set", schema, key, value]).returncode == 0


def _custom_keybindings() -> list[str]:
    raw = _gsettings_get(MEDIA_KEYS_SCHEMA, "custom-keybindings")
    raw = raw.removeprefix("@as ").strip()
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def install_keybinding(accelerator: str = DEFAULT_HOTKEY) -> bool:
    return set_keybinding(accelerator)


def set_keybinding(accelerator: str) -> bool:
    """Rebind the app's shortcut, keeping the entry registered.

    Refuses anything that is not a real shortcut, so a bad value cannot leave
    the app unreachable with no way to open it.
    """
    if not hotkey.is_valid(accelerator):
        return False
    if not shutil.which("gsettings"):
        return False
    existing = _custom_keybindings()
    if KEYBINDING_PATH not in existing:
        existing.append(KEYBINDING_PATH)
        _gsettings_set(MEDIA_KEYS_SCHEMA, "custom-keybindings", repr(existing))
    _gsettings_set(KEYBINDING_SCHEMA, "name", APP_NAME)
    _gsettings_set(KEYBINDING_SCHEMA, "command", f"{_exec_path()} toggle")
    return _gsettings_set(KEYBINDING_SCHEMA, "binding", accelerator)


def current_keybinding() -> str:
    """The shortcut currently bound to the app, as an accelerator.

    Falls back to the default when nothing usable is stored, so the settings
    always has something to show.
    """
    if not shutil.which("gsettings"):
        return DEFAULT_HOTKEY
    stored = _gsettings_get(KEYBINDING_SCHEMA, "binding").strip().strip("'")
    return stored if hotkey.is_valid(stored) else DEFAULT_HOTKEY


def remove_keybinding() -> bool:
    if not shutil.which("gsettings"):
        return False
    existing = [p for p in _custom_keybindings() if p != KEYBINDING_PATH]
    _gsettings_set(MEDIA_KEYS_SCHEMA, "custom-keybindings", repr(existing))
    return True


def install_service() -> Path:
    path = _service_dir() / SERVICE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        SERVICE_TEMPLATE.format(
            app=APP_NAME, exec_path=_exec_path(), env_extra=_env_extra()
        ),
        encoding="utf-8",
    )
    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", SERVICE_NAME])
    return path


def uninstall_service() -> None:
    _run(["systemctl", "--user", "disable", "--now", SERVICE_NAME])
    path = _service_dir() / SERVICE_NAME
    path.unlink(missing_ok=True)
    _run(["systemctl", "--user", "daemon-reload"])


# --------------------------------------------------------------- extension


def _extensions_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "gnome-shell" / "extensions"


# --------------------------------------------------------------- icons


def _icons_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "icons" / "hicolor"


def _icon_source() -> Path:
    return Path(__file__).resolve().parent / "icons"


# Sizes written into the user's icon theme. The source is the 512px artwork,
# scaled down so every place GNOME asks for an icon has a fitting one.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def install_icons() -> bool:
    """Place the app icon in the user's icon theme, at several sizes.

    The artwork is a detailed illustration, so it is pre-scaled here rather
    than left to the theme's own downscaling: at 16-24px the difference is
    visible in the launcher. A symbolic (line-art) variant is installed too,
    under the name the top bar asks for.
    """
    source = _icon_source() / "simplecopypaste.png"
    if not source.exists():
        return False
    try:
        from .gtk_ui import GdkPixbuf
    except Exception as exc:
        print(f"  could not load the icon renderer: {exc}", file=sys.stderr)
        return False

    installed = False
    for size in ICON_SIZES:
        target = _icons_dir() / f"{size}x{size}" / "apps" / "simplecopypaste.png"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(source), size, size, True
            )
            pixbuf.savev(str(target), "png", [], [])
            installed = True
        except Exception as exc:
            print(f"  could not install icon {size}px: {exc}", file=sys.stderr)

    # The symbolic mark goes into the theme by name; the shell recolours it
    # to match a light or dark top bar. See PANEL_ICON_SYMBOLIC.
    symbolic_source = _icon_source() / PANEL_ICON_SYMBOLIC
    if symbolic_source.exists():
        try:
            target = (
                _icons_dir() / "symbolic" / "apps" / f"{PANEL_ICON_NAME_SYMBOLIC}.svg"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(symbolic_source, target)
            installed = True
        except OSError as exc:
            print(f"  could not install the symbolic icon: {exc}", file=sys.stderr)

    # An older build installed a scalable glyph under the plain name; it
    # would take priority at large sizes and shadow this artwork.
    (_icons_dir() / "scalable" / "apps" / "simplecopypaste.svg").unlink(missing_ok=True)

    if installed:
        _run(["gtk-update-icon-cache", "--force", "--ignore-theme-index", str(_icons_dir())])
    return installed


def _extension_source() -> Path:
    return Path(__file__).resolve().parent / "gnome_extension"


DESKTOP_NAME = "simplecopypaste.desktop"
DESKTOP_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name={app}
Comment=Clipboard history at your cursor
Exec={exec_path} settings
Icon=simplecopypaste
Terminal=false
Categories=Utility;GTK;
StartupNotify=true
StartupWMClass=Simpleclips
"""


def _applications_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "applications"


def install_desktop() -> Path:
    """Write the launcher entry.

    Needed for the dash and the app grid: it is what makes the running
    settings window show up with our icon and name, and gives the app an
    entry to launch from. ``StartupWMClass`` matches the window's WM_CLASS
    so GNOME ties the window to this entry.
    """
    path = _applications_dir() / DESKTOP_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        DESKTOP_TEMPLATE.format(app=APP_NAME, exec_path=_exec_path()),
        encoding="utf-8",
    )
    _run(["update-desktop-database", str(_applications_dir())])
    return path


def remove_desktop() -> None:
    (_applications_dir() / DESKTOP_NAME).unlink(missing_ok=True)
    _run(["update-desktop-database", str(_applications_dir())])


# The top bar draws its icons at about 16px, where the detailed illustration
# turns to mush, and it asks for a *symbolic* icon: a single ink colour the
# shell replaces with the theme foreground, so the mark follows a light or
# dark bar. Two files serve that:
#
#   * panel-symbolic.svg — installed into the theme, looked up by name, and
#     therefore recoloured. This is the one the panel normally uses.
#   * panel.png — a ready-coloured fallback bundled inside the extension, for
#     when the theme copy is missing (the app running from a checkout).
PANEL_ICON_SYMBOLIC = "panel-symbolic.svg"
PANEL_ICON_NAME_SYMBOLIC = "simplecopypaste-symbolic"
PANEL_ICON_SOURCE = "panel.png"
PANEL_ICON_NAME = "panel.png"

# Files shipped by earlier builds that no longer belong in the extension
# folder. Removed on install so a stale copy cannot shadow the current one.
OBSOLETE_EXTENSION_FILES = ["simplecopypaste.svg", "simplecopypaste.png"]


def is_gnome_session() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return "gnome" in desktop or "ubuntu" in desktop


def extension_installed() -> bool:
    return (_extensions_dir() / EXTENSION_UUID / "extension.js").exists()


def _gnome_extensions_cli() -> str | None:
    return shutil.which("gnome-extensions")


def _extension_enabled_state() -> str:
    cli = _gnome_extensions_cli()
    if cli is None:
        return "unknown"
    proc = _run([cli, "info", EXTENSION_UUID])
    if proc.returncode != 0:
        return "missing"
    for line in proc.stdout.splitlines():
        if line.startswith("State:"):
            return line.split(":", 1)[1].strip().upper()
    return "unknown"


SHELL_SCHEMA = "org.gnome.shell"


def _enabled_extensions() -> list[str]:
    raw = _gsettings_get(SHELL_SCHEMA, "enabled-extensions")
    raw = raw.removeprefix("@as ").strip()
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _set_enabled_extensions(uuids: list[str]) -> None:
    _gsettings_set(SHELL_SCHEMA, "enabled-extensions", repr(uuids))


def _copy_icon_into(target: Path) -> None:
    """Place the panel glyph next to the extension, for its top-bar button."""
    origin = _icon_source() / PANEL_ICON_SOURCE
    if origin.exists():
        shutil.copyfile(origin, target / PANEL_ICON_NAME)


def install_extension(hotkey_note: list[str]) -> None:
    """Install the companion GNOME Shell extension if we are on GNOME."""
    if not is_gnome_session():
        return
    source = _extension_source()
    target = _extensions_dir() / EXTENSION_UUID
    try:
        # Copy over the existing files; never remove the directory first.
        # While the extension is running, the Shell keeps a handle on it, and
        # deleting the folder out from under it leaves the extension disabled
        # and unable to reload (Wayland cannot reload the Shell).
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.is_file():
                shutil.copyfile(item, target / item.name)
        _copy_icon_into(target)
        for stale in OBSOLETE_EXTENSION_FILES:
            (target / stale).unlink(missing_ok=True)
    except OSError as exc:
        print(f"  could not install the GNOME extension: {exc}", file=sys.stderr)
        return

    # Register it as enabled in gsettings, so it stays enabled across logins.
    if shutil.which("gsettings"):
        uuids = _enabled_extensions()
        if EXTENSION_UUID not in uuids:
            _set_enabled_extensions(uuids + [EXTENSION_UUID])

    state = _extension_enabled_state()
    if state in ("ENABLED", "ACTIVE"):
        hotkey_note.append(
            "already active. To pick up changes to its code, log out and "
            "back in (Wayland cannot reload the Shell in place)."
        )
        return

    # Only poke the Shell when it is not already running the extension.
    cli = _gnome_extensions_cli()
    if cli is not None:
        _run([cli, "enable", EXTENSION_UUID])

    state = _extension_enabled_state()
    if state in ("ENABLED", "ACTIVE"):
        hotkey_note.append(
            "installed and registered. Log out and back in once so the "
            "running Shell loads it (Wayland cannot reload the Shell)."
        )
    else:
        hotkey_note.append(
            "installed. Log out and back in, then run "
            f"'gnome-extensions enable {EXTENSION_UUID}' if needed."
        )


def remove_extension() -> None:
    if shutil.which("gsettings"):
        uuids = [u for u in _enabled_extensions() if u != EXTENSION_UUID]
        _set_enabled_extensions(uuids)
    cli = _gnome_extensions_cli()
    if cli is not None:
        _run([cli, "disable", EXTENSION_UUID])
    target = _extensions_dir() / EXTENSION_UUID
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def extension_status() -> str:
    if not extension_installed():
        return "not installed"
    return _extension_enabled_state().lower()


def install(hotkey: str = "<Super><Alt>v") -> int:
    if not _on_path():
        print(
            "warning: 'simplecopypaste' is not on PATH; install it first, e.g.\n"
            "    pipx install --system-site-packages .\n"
            "otherwise the service and shortcut may not find the command.",
            file=sys.stderr,
        )
    service = install_service()
    print(f"systemd user service: {service}")
    if install_icons():
        print(f"app icon: {_icons_dir() / '512x512' / 'apps' / 'simplecopypaste.png'}")
    print(f"launcher entry: {install_desktop()}")
    if install_keybinding(hotkey):
        print(f"GNOME shortcut: {hotkey} -> simplecopypaste toggle")
    else:
        print("gsettings not found: bind a shortcut manually to 'simplecopypaste toggle'")

    notes: list[str] = []
    install_extension(notes)
    for note in notes:
        print(f"GNOME extension: {note}")

    print("Done. Press the shortcut to open SimpleCopyPaste.")
    return 0


def uninstall() -> int:
    uninstall_service()
    remove_keybinding()
    remove_extension()
    remove_desktop()
    print("SimpleCopyPaste removed from the desktop session.")
    return 0
