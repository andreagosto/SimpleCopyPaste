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

SERVICE_NAME = "simpleclips.service"
EXTENSION_UUID = "simpleclips@simpleclips.github.io"
KEYBINDING_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/simpleclips/"
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
    found = shutil.which("simpleclips")
    if found:
        return found
    return f"{sys.executable} -m simpleclips"


def _on_path() -> bool:
    return shutil.which("simpleclips") is not None


def _env_extra() -> str:
    """Running from a source checkout needs PYTHONPATH to find the package."""
    if _on_path():
        return ""
    src = Path(__file__).resolve().parents[1]
    return f"Environment=PYTHONPATH={src}"


def _run(argv: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=check)


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


def install_keybinding(hotkey: str = "<Super><Alt>v") -> bool:
    if not shutil.which("gsettings"):
        return False
    existing = _custom_keybindings()
    if KEYBINDING_PATH not in existing:
        existing.append(KEYBINDING_PATH)
        _gsettings_set(MEDIA_KEYS_SCHEMA, "custom-keybindings", repr(existing))
    _gsettings_set(KEYBINDING_SCHEMA, "name", APP_NAME)
    _gsettings_set(KEYBINDING_SCHEMA, "command", f"{_exec_path()} toggle")
    _gsettings_set(KEYBINDING_SCHEMA, "binding", hotkey)
    return True


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


def install_icons() -> bool:
    """Place the app icon in the user's icon theme.

    Both a scalable SVG and a 512px PNG are installed, so it resolves at any
    size for the settings window, task switcher, notifications and menus.
    """
    source = _icon_source()
    targets = [
        (_icons_dir() / "scalable" / "apps" / "simpleclips.svg", source / "simpleclips.svg"),
        (_icons_dir() / "512x512" / "apps" / "simpleclips.png", source / "simpleclips.png"),
    ]
    installed = False
    for target, origin in targets:
        if not origin.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            installed = True
        except OSError as exc:
            print(f"  could not install icon {target.name}: {exc}", file=sys.stderr)
    if installed:
        _run(["gtk-update-icon-cache", "--force", "--ignore-theme-index", str(_icons_dir())])
    return installed


def _extension_source() -> Path:
    return Path(__file__).resolve().parent / "gnome_extension"


# Files copied into the extension folder, beyond its own JS/JSON. The panel
# icon is bundled so the top-bar button works regardless of the icon theme.
EXTENSION_EXTRAS = ["simpleclips.svg", "simpleclips.png"]


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
    """Place the app icon next to the extension, for its panel button."""
    source = _icon_source()
    for name in EXTENSION_EXTRAS:
        origin = source / name
        if origin.exists():
            shutil.copyfile(origin, target / name)


def install_extension(hotkey_note: list[str]) -> None:
    """Install the companion GNOME Shell extension if we are on GNOME."""
    if not is_gnome_session():
        return
    source = _extension_source()
    target = _extensions_dir() / EXTENSION_UUID
    try:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        _copy_icon_into(target)
    except OSError as exc:
        print(f"  could not install the GNOME extension: {exc}", file=sys.stderr)
        return

    # Register it as enabled directly, so it is active after the next login
    # even though the running Shell has not scanned the new directory yet.
    if shutil.which("gsettings"):
        uuids = _enabled_extensions()
        if EXTENSION_UUID not in uuids:
            _set_enabled_extensions(uuids + [EXTENSION_UUID])

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
            "warning: 'simpleclips' is not on PATH; install it first, e.g.\n"
            "    pipx install --system-site-packages .\n"
            "otherwise the service and shortcut may not find the command.",
            file=sys.stderr,
        )
    service = install_service()
    print(f"systemd user service: {service}")
    if install_icons():
        print(f"app icon: {_icons_dir() / 'scalable' / 'apps' / 'simpleclips.svg'}")
    if install_keybinding(hotkey):
        print(f"GNOME shortcut: {hotkey} -> simpleclips toggle")
    else:
        print("gsettings not found: bind a shortcut manually to 'simpleclips toggle'")

    notes: list[str] = []
    install_extension(notes)
    for note in notes:
        print(f"GNOME extension: {note}")

    print("Done. Press the shortcut to open SimpleClips.")
    return 0


def uninstall() -> int:
    uninstall_service()
    remove_keybinding()
    remove_extension()
    print("SimpleClips removed from the desktop session.")
    return 0
