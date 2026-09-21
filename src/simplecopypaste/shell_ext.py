"""Client for the SimpleCopyPaste GNOME Shell companion extension.

The extension exposes, over the session bus:

  * ``GetPointer`` — the global cursor position (Wayland hides it from
    applications, and the XWayland pointer goes stale over Wayland windows).
  * ``Paste`` — a synthesized key combo, so picking a clip can paste it.

Using the extension means no ydotool, no ``/dev/uinput`` permissions and no
extra daemon. When it is not installed we fall back to whatever the session
offers (X11 pointer, ydotool/xdotool for pasting).

Two address are probed: the current ``org.simplecopypaste.Shell`` object and the
earlier ``org.simplecopypaste.Pointer`` one. GNOME loads extension code only at
login, so an updated extension keeps answering on the old object until the
user logs out; supporting both avoids breaking anything in between.
"""

from __future__ import annotations

import time

from .gtk_ui import GLib, Gio

DBUS_NAME = "org.gnome.Shell"
TIMEOUT_MS = 400
RETRY_AFTER = 15.0

# (object path, interface) — newest first.
ENDPOINTS = [
    ("/org/simplecopypaste/Shell", "org.simplecopypaste.Shell"),
    ("/org/simplecopypaste/Pointer", "org.simplecopypaste.Pointer"),  # legacy
]


class ShellExtension:
    """Cached D-Bus client for the companion extension."""

    def __init__(self) -> None:
        self._connection = None
        self._state: bool | None = None
        self._last_failure = 0.0
        self._endpoint: tuple[str, str] | None = None
        self._signal_ids: list[int] = []

    def _conn(self):
        if self._connection is None:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return self._connection

    def _call(self, method: str, params=None, endpoint=None, timeout: int = TIMEOUT_MS):
        path, iface = endpoint or self._endpoint or ENDPOINTS[0]
        return self._conn().call_sync(
            DBUS_NAME,
            path,
            iface,
            method,
            params,
            None,
            Gio.DBusCallFlags.NONE,
            timeout,
            None,
        )

    # ------------------------------------------------------------ discovery

    def _resolve_endpoint(self) -> tuple[str, str] | None:
        for endpoint in ENDPOINTS:
            try:
                self._call("Ping", endpoint=endpoint, timeout=250)
                return endpoint
            except Exception:
                try:
                    # The legacy object has no Ping; GetPointer proves it too.
                    self._call("GetPointer", endpoint=endpoint, timeout=250)
                    return endpoint
                except Exception:
                    continue
        return None

    def available(self) -> bool:
        """True when the extension answers on the bus.

        A failure is remembered briefly so we do not pay a D-Bus timeout on
        every call when the extension is absent, while still picking it up
        once it appears (it loads at login).
        """
        if self._state is True:
            return True
        if self._state is False and (time.time() - self._last_failure) < RETRY_AFTER:
            return False
        endpoint = self._resolve_endpoint()
        self._endpoint = endpoint
        self._state = endpoint is not None
        if endpoint is None:
            self._last_failure = time.time()
        return self._state

    # ------------------------------------------------------------ features

    def get_pointer(self) -> tuple[int, int] | None:
        if not self.available():
            return None
        try:
            result = self._call("GetPointer")
            x, y = result.unpack()
        except Exception:
            return None
        return int(x), int(y)

    def paste(self, combo: str = "ctrl+v") -> bool:
        if not self.available():
            return False
        try:
            result = self._call("Paste", GLib.Variant("(sb)", (combo, False)))
        except Exception:
            return False
        try:
            return bool(result.unpack()[0])
        except Exception:
            return False

    def can_paste(self, combo: str = "ctrl+v") -> bool:
        """Check the combo is supported, without injecting anything."""
        if not self._has_paste():
            return False
        try:
            result = self._call("Paste", GLib.Variant("(sb)", (combo, True)))
            return bool(result.unpack()[0])
        except Exception:
            return False

    def _has_paste(self) -> bool:
        if not self.available():
            return False
        if self._endpoint is None:
            return False
        return self._endpoint[1] == "org.simplecopypaste.Shell"

    # ------------------------------------------------------- click watching

    def set_click_watch(self, on: bool) -> bool:
        """Ask the extension to report clicks it sees on its own surfaces."""
        if not self.available():
            return False
        endpoint = self._endpoint
        if endpoint is None or endpoint[1] != "org.simplecopypaste.Shell":
            return False
        try:
            result = self._call("SetClickWatch", GLib.Variant("(b)", (bool(on),)))
        except Exception:
            return False
        try:
            return bool(result.unpack()[0])
        except Exception:
            return False

    def subscribe_clicked(self, callback) -> bool:
        """Run *callback* whenever the extension says the panel should close.

        That is a click on a shell surface, or focus moving to another window.
        The callback receives no arguments. Returns False when the extension
        cannot provide the signal (older build, or not installed).
        """
        if not self.available():
            return False
        endpoint = self._endpoint
        if endpoint is None or endpoint[1] != "org.simplecopypaste.Shell":
            return False
        if self._signal_ids:
            return True

        def _dispatch(*_args):
            # The exact argument list of a Gio signal callback varies with
            # the binding version (a trailing user_data, or not), so accept
            # whatever arrives rather than naming them.
            try:
                callback()
            except Exception:
                pass

        # "Dismiss" is the current name; "Clicked" is what earlier builds
        # emitted, kept so an extension that is still loaded from a previous
        # login keeps working.
        for name in ("Dismiss", "Clicked"):
            try:
                # Filter on interface, signal and path but not on the sender:
                # the shell's bus name is the natural filter, yet leaving it
                # out costs nothing (the other three already pin it down) and
                # avoids depending on how the shell names itself.
                signal_id = self._conn().signal_subscribe(
                    None,
                    endpoint[1],
                    name,
                    endpoint[0],
                    None,
                    Gio.DBusSignalFlags.NONE,
                    _dispatch,
                )
            except Exception:
                continue
            if signal_id:
                self._signal_ids.append(signal_id)
        return bool(self._signal_ids)
