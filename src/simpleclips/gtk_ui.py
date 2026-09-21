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

__all__ = ["Gdk", "GdkPixbuf", "Gio", "GLib", "Gtk", "Pango"]
