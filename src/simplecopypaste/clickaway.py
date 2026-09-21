"""Close a window when the user clicks outside it.

Two mechanisms, because neither covers every case on GNOME Wayland:

* **Focus loss** — covers clicking another window. The click moves keyboard
  focus away, and GTK reports it. On a bare X11 session this is enough.
* **Click reports from the shell extension** — covers clicks that land on
  surfaces the shell owns, the desktop above all. Those do not move focus at
  all (the previously focused window stays focused), so nothing tells the app
  about them, and they never reach an XWayland client either. The extension
  watches the shell stage and tells us instead.

Clicks *inside* the window raise both: the window receives the press itself.
They are told apart by timing — a click the window handled itself is recorded
around the same instant the report arrives, so a recent internal click makes
the report a no-op.
"""

from __future__ import annotations

import time

from .shell_ext import ShellExtension

# Ignore clicks arriving this soon after the window appeared: the very click
# that opened it (on the panel icon, say) can still be in flight.
CLICK_GRACE = 0.20

# How close an internal click has to be to a report for the report to count
# as that same click.
INTERNAL_CLICK_WINDOW = 0.25


def should_close_on_click(
    visible: bool,
    shown_at: float,
    last_internal_click: float,
    now: float,
    grace: float = CLICK_GRACE,
    internal_window: float = INTERNAL_CLICK_WINDOW,
) -> bool:
    """Whether a click reported by the shell should close the window."""
    if not visible:
        return False
    if (now - shown_at) < grace:
        return False
    if last_internal_click and (now - last_internal_click) < internal_window:
        return False
    return True


class ClickAway:
    """Bridges the shell extension's click reports to a callback."""

    def __init__(self, on_outside_click) -> None:
        self.shell = ShellExtension()
        self._on_outside_click = on_outside_click
        self._subscribed = False
        self._watching = False

    def start(self) -> bool:
        """Begin reporting. False when the extension cannot do it."""
        if not self.shell.available():
            return False
        if not self._subscribed:
            self._subscribed = self.shell.subscribe_clicked(self._on_report)
            if not self._subscribed:
                return False
        ok = self.shell.set_click_watch(True)
        self._watching = ok
        return ok

    def stop(self) -> None:
        if self._watching:
            self.shell.set_click_watch(False)
            self._watching = False

    def _on_report(self) -> None:
        if not self._watching:
            return
        try:
            self._on_outside_click()
        except Exception:
            pass


def now() -> float:
    return time.time()
