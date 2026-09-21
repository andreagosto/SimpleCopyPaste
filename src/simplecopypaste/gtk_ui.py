"""Single place that configures GTK 3 + X11 backend before import.

Positioning the popup at the pointer only works when GTK talks X11. On a
Wayland session we therefore ask GTK to use its X11 backend (XWayland),
which GNOME/Ubuntu provide out of the box. This module must be imported
before any other GTK usage so the environment is set in time.
"""

from __future__ import annotations

import os

# Position-at-pointer only works when GTK talks X11 (XWayland on GNOME),
# and so does the clipboard owner-change signal used to watch for copies.
# Force the X11 backend only when an X server is actually reachable, so a
# Wayland session without XWayland still starts.
if "GDK_BACKEND" not in os.environ and os.environ.get("WAYLAND_DISPLAY"):
    if os.environ.get("DISPLAY"):
        os.environ["GDK_BACKEND"] = "x11"

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402,F401

__all__ = [
    "Gdk",
    "GdkPixbuf",
    "Gio",
    "GLib",
    "Gtk",
    "Pango",
    "set_app_icon",
    "should_autohide",
]

# A window ignores focus loss for this long after appearing. Showing a window
# briefly moves focus around, and without the grace period the window would
# close itself on the spot.
FOCUS_OUT_GRACE = 0.25


def should_autohide(
    visible: bool, shown_at: float, now: float, grace: float = FOCUS_OUT_GRACE
) -> bool:
    """Whether losing focus should close a popup/settings window."""
    return bool(visible) and (now - shown_at) > grace


def any_popup_open(combos) -> bool:
    """True while one of these combo boxes has its dropdown open.

    A dropdown lives in its own toplevel, so opening it moves focus away from
    the window and looks exactly like a click elsewhere. ``is_active()`` on
    that popup toplevel is not dependable, but each combo reports this
    property reliably (``notify::popup-shown``).
    """
    for combo in combos:
        try:
            if combo.get_property("popup-shown"):
                return True
        except Exception:
            continue
    return False


def set_app_icon() -> None:
    """Use the bundled icon for our windows.

    Loaded from the package rather than the icon theme, so the settings
    window and dialogs look right even before ``simplecopypaste install``.
    """
    path = os.path.join(os.path.dirname(__file__), "icons", "simplecopypaste.png")
    if not os.path.exists(path):
        return
    try:
        Gtk.Window.set_default_icon_from_file(path)
    except Exception:
        pass
