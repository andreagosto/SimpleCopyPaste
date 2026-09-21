"""Synthetic paste (Ctrl+V and friends).

Priority order:

1. **SimpleCopyPaste GNOME Shell extension** — works on GNOME Wayland with no
   extra dependency. It asks the compositor to press the combo.
2. **ydotool** — the generic Wayland path, needs the tool installed and its
   daemon running (``/dev/uinput`` access).
3. **xdotool** — X11 sessions.

When nothing is usable the popup still copies the clip; the user just
presses the paste shortcut themselves, and a discreet hint says so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from .shell_ext import ShellExtension

# Linux input event codes, for the ydotool path.
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_V = 47

INSTALL_HINTS = {
    "debian": "sudo apt install ydotool",
    "ubuntu": "sudo apt install ydotool",
    "fedora": "sudo dnf install ydotool",
    "arch": "sudo pacman -S ydotool",
    "opensuse": "sudo zypper install ydotool",
}

DEFAULT_COMBO = "ctrl+v"


def detect(combo: str = DEFAULT_COMBO) -> str:
    """Return the best available paste backend name."""
    if os.environ.get("WAYLAND_DISPLAY"):
        extension = ShellExtension()
        if extension.available() and extension.can_paste(combo):
            return "gnome-shell"
        if shutil.which("ydotool"):
            return "ydotool"
        return "none"
    if shutil.which("xdotool"):
        return "xdotool"
    if shutil.which("ydotool"):
        return "ydotool"
    return "none"


def install_hint() -> str | None:
    """A concrete command for the user, or None when nothing is missing."""
    if shutil.which("ydotool"):
        return None
    return INSTALL_HINTS.get(_distro_id(), "install ydotool from your package manager")


def extension_hint() -> str:
    return (
        "Enable the SimpleCopyPaste GNOME extension for automatic pasting "
        "(run 'simplecopypaste install', then log out and back in)."
    )


def _distro_id() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


def send_paste(
    backend: str | None = None,
    combo: str = DEFAULT_COMBO,
    delay: float = 0.18,
) -> bool:
    """Press the paste combo. Returns True if a backend accepted the request."""
    backend = backend or detect(combo)
    if delay:
        time.sleep(delay)

    if backend == "gnome-shell":
        return ShellExtension().paste(combo)

    if backend in ("ydotool", "xdotool"):
        return _send_via_tool(backend, combo)
    return False


def _combo_to_keycodes(combo: str) -> list[int] | None:
    """Translate ``ctrl+shift+v`` into Linux key codes for ydotool."""
    aliases = {
        "ctrl": KEY_LEFTCTRL,
        "control": KEY_LEFTCTRL,
        "shift": KEY_LEFTSHIFT,
        "v": KEY_V,
    }
    codes: list[int] = []
    for part in combo.lower().split("+"):
        part = part.strip()
        if not part:
            continue
        code = aliases.get(part)
        if code is None:
            return None
        codes.append(code)
    return codes or None


def _send_via_tool(backend: str, combo: str) -> bool:
    if backend == "xdotool":
        pretty = combo.replace("ctrl", "ctrl").replace("+", "+")
        try:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", pretty],
                check=False,
                capture_output=True,
                timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    codes = _combo_to_keycodes(combo)
    if not codes:
        return False
    keys = [f"{code}:1" for code in codes] + [f"{code}:0" for code in reversed(codes)]
    try:
        subprocess.run(
            ["ydotool", "key", *keys],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
