"""Reading the X server time.

Needed to give a window focus. Mutter refuses to focus a window whose
``_NET_WM_USER_TIME`` is older than the last user interaction, which is how
focus stealing is prevented. Our daemon is started at login and never sees a
user event, so the timestamp GTK would use is 0: the popup opened but never
received the keyboard, and typing into it did nothing.

The X server time is not exposed by GTK without an event, so it is sampled
directly: change a property on a throwaway window and read the timestamp from
the resulting PropertyNotify.
"""

from __future__ import annotations

import ctypes
import time

PropertyChangeMask = 1 << 22
XA_STRING = 31
PropModeReplace = 0


class XPropertyEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("atom", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("state", ctypes.c_int),
    ]


class XEvent(ctypes.Union):
    """A whole XEvent.

    Xlib writes a full XEvent (24 longs) into the pointer it is given, so the
    buffer must be that size even though only the XPropertyEvent part is read.
    Passing the smaller struct lets Xlib write past it and corrupts memory,
    which showed up as a segfault after a few dozen calls.
    """

    _fields_ = [("pad", ctypes.c_long * 24)]


def _lib():
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XCreateSimpleWindow.restype = ctypes.c_ulong
    x11.XCreateSimpleWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong,
    ]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    x11.XChangeProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
    ]
    x11.XWindowEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long, ctypes.POINTER(XEvent)
    ]
    # Non-blocking variant: returns 0 when nothing is queued for us.
    x11.XCheckWindowEvent.restype = ctypes.c_int
    x11.XCheckWindowEvent.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long, ctypes.POINTER(XEvent)
    ]
    x11.XConnectionNumber.restype = ctypes.c_int
    x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x11.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x11


def server_time(timeout: float = 0.2) -> int:
    """The current X server time in milliseconds, or 0 when unavailable."""
    try:
        x11 = _lib()
        display = x11.XOpenDisplay(None)
    except (OSError, AttributeError):
        return 0
    if not display:
        return 0

    window = 0
    try:
        window = x11.XCreateSimpleWindow(
            display, x11.XDefaultRootWindow(display), -10, -10, 1, 1, 0, 0, 0
        )
        x11.XSelectInput(display, window, PropertyChangeMask)
        atom = x11.XInternAtom(display, b"_SIMPLECOPYPASTE_TIME", False)
        x11.XChangeProperty(
            display, window, atom, XA_STRING, 8, PropModeReplace, b"t", 1
        )

        # Poll instead of select(): Xlib reads ahead into its own queue, so the
        # event is often already buffered and the socket looks idle.
        raw = XEvent()
        deadline = time.monotonic() + timeout
        while x11.XCheckWindowEvent(
            display, window, PropertyChangeMask, ctypes.byref(raw)
        ) == 0:
            if time.monotonic() >= deadline:
                return 0
            time.sleep(0.002)
        event = ctypes.cast(ctypes.byref(raw), ctypes.POINTER(XPropertyEvent)).contents
        return int(event.time)
    except Exception:
        return 0
    finally:
        try:
            if window:
                x11.XDestroyWindow(display, window)
            x11.XCloseDisplay(display)
        except Exception:
            pass
