"""Global pointer position.

On X11 ``XQueryPointer`` (what GDK uses) is exact. On Wayland it is not:
the XWayland pointer is only updated while the cursor is over an X11
surface, so a Wayland-native window (or the desktop) leaves it stale.

For GNOME the companion Shell extension reports the compositor's real
pointer; we use it when present and fall back to the X pointer otherwise
(which is correct on X11 sessions).
"""

from __future__ import annotations

from .gtk_ui import Gdk
from .shell_ext import ShellExtension


def x11_pointer() -> tuple[int, int] | None:
    display = Gdk.Display.get_default()
    if display is None:
        return None
    seat = display.get_default_seat()
    if seat is None:
        return None
    pointer = seat.get_pointer()
    if pointer is None:
        return None
    try:
        result = pointer.get_position()
    except Exception:
        return None
    if not result:
        return None
    if len(result) == 3:
        _screen, x, y = result
    elif len(result) == 2:
        x, y = result
    else:
        return None
    return int(x), int(y)


class Pointer:
    """Best-effort global cursor position, with the source it came from."""

    def __init__(self) -> None:
        self.extension = ShellExtension()

    def get(self) -> tuple[int, int, str] | None:
        point = self.extension.get_pointer() if self.extension.available() else None
        if point is not None:
            return point[0], point[1], "gnome-shell"
        point = x11_pointer()
        if point is not None:
            return point[0], point[1], "x11"
        return None

    def source(self) -> str:
        if self.extension.available():
            return "gnome-shell"
        if x11_pointer() is not None:
            return "x11"
        return "none"
