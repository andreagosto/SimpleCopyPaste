"""Clipboard access: Wayland (wl-clipboard) and X11 (xclip) backends.

Supports both text and images. Images are returned as raw bytes together
with the MIME type they were announced under, so they can be put back on
the clipboard unchanged.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

# Preferred text MIME types, best first.
TEXT_MIMES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING")

# Preferred image MIME types, best first.
IMAGE_MIMES = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
)

# File managers copy *files* as a list of URIs, not as their content, so a
# copied picture arrives as a path. These are the types that carry it.
URI_LIST_MIMES = ("text/uri-list", "x-special/gnome-copied-files")

# A file-backed image is read into memory before the pixel check, so refuse
# absurd sizes up front. The daemon applies its own limits afterwards.
MAX_FILE_BYTES = 64 * 1024 * 1024


class ClipboardError(RuntimeError):
    pass


def _file_uri_to_path(uri: str) -> str | None:
    """Turn a file:// URI into a local path, or None if it is not local."""
    try:
        parsed = urlparse(uri.strip())
    except ValueError:
        return None
    if parsed.scheme != "file":
        return None
    if parsed.netloc not in ("", "localhost"):
        return None
    return url2pathname(unquote(parsed.path))


def parse_uri_list(raw: str) -> list[str]:
    """Parse a text/uri-list body (RFC 2483 + the GNOME 'copy' prefix)."""
    uris: list[str] = []
    for line in raw.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry in ("copy", "cut"):
            continue
        uris.append(entry)
    return uris



def _run(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, timeout=timeout)


def _run_text(argv: list[str], timeout: float = 5.0) -> str:
    proc = _run(argv, timeout=timeout)
    if proc.returncode != 0:
        raise ClipboardError(
            f"{' '.join(argv)} exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout.decode("utf-8", "replace")


class Clipboard:
    """Read/write the system clipboard using the best available backend."""

    def __init__(self) -> None:
        self._backend = self._detect()
        # When true, copying an image *file* yields the image rather than
        # its path. Set by the daemon from the config.
        self.resolve_image_files = True

    @property
    def backend(self) -> str:
        return self._backend

    def available(self) -> bool:
        return self._backend != "none"

    @staticmethod
    def _detect() -> str:
        have = shutil.which
        if os.environ.get("WAYLAND_DISPLAY") and have("wl-paste") and have("wl-copy"):
            return "wayland"
        if os.environ.get("DISPLAY") and have("xclip"):
            return "x11"
        if have("wl-paste") and have("wl-copy"):
            return "wayland"
        if have("xclip"):
            return "x11"
        return "none"

    # ----------------------------------------------------------- inspection

    def list_types(self) -> list[str]:
        try:
            if self._backend == "wayland":
                out = _run_text(["wl-paste", "--list-types"])
            elif self._backend == "x11":
                out = _run_text(
                    ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"]
                )
            else:
                return []
        except (ClipboardError, subprocess.TimeoutExpired, FileNotFoundError):
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def signature(self) -> str:
        """Cheap change-detector for polling; avoids fetching image bytes.

        On X11 the ``TIMESTAMP`` target changes on every selection change,
        which detects new images without hashing their (possibly large)
        contents. Elsewhere we fall back to the advertised MIME types.
        """
        types = self.list_types()
        base = "|".join(sorted(types))
        if self._backend == "x11" and "TIMESTAMP" in types:
            stamp = self.get_bytes("TIMESTAMP")
            if stamp:
                return stamp.hex() + "|" + base
        return base

    # ----------------------------------------------------------------- read

    def read(self) -> Optional[dict]:
        """Read the best available representation.

        Returns one of:
          {"kind": "text",  "text": str}
          {"kind": "image", "data": bytes, "mime": str}
        or None when the clipboard holds nothing usable.
        """
        types = self.list_types()
        if not types:
            return None

        # A copied image file announces its path; load the picture itself.
        # This must come before the text fallback, because the same copy
        # also exposes the path as plain text.
        if self.resolve_image_files and any(m in types for m in URI_LIST_MIMES):
            payload = self._read_uri_image(types)
            if payload is not None:
                return payload

        for mime in TEXT_MIMES:
            if mime in types:
                text = self.get_text(mime)
                if text.strip():
                    return {"kind": "text", "text": text}
                break

        for mime in IMAGE_MIMES:
            if mime in types:
                data = self.get_bytes(mime)
                if data:
                    return {"kind": "image", "data": data, "mime": mime}
        return None

    def _read_uri_image(self, types: list[str]) -> Optional[dict]:
        """Load a copied image file, when the clipboard names exactly one."""
        raw = ""
        for mime in URI_LIST_MIMES:
            if mime in types:
                raw = self.get_text(mime)
                if raw:
                    break
        if not raw:
            return None

        uris = parse_uri_list(raw)
        if len(uris) != 1:
            return None  # several files: keep the plain text listing

        path = _file_uri_to_path(uris[0])
        if not path or not os.path.isfile(path):
            return None

        mime, _ = mimetypes.guess_type(path)
        # Only hand back formats we can actually decode later; anything
        # else (SVG, HEIC, ...) is left as the plain path.
        if mime not in IMAGE_MIMES:
            return None

        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                return None
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return None
        if not data:
            return None
        return {"kind": "image", "data": data, "mime": mime, "source": path}

    def get_text(self, mime: str = "text/plain;charset=utf-8") -> str:
        data = self.get_bytes(mime)
        if not data:
            return ""
        return data.decode("utf-8", "replace")

    def get_bytes(self, mime: str) -> bytes:
        try:
            if self._backend == "wayland":
                argv = ["wl-paste", "--type", mime]
                if mime.startswith("text/"):
                    # wl-paste appends a newline unless told otherwise.
                    argv.insert(1, "--no-newline")
            elif self._backend == "x11":
                argv = ["xclip", "-selection", "clipboard", "-o", "-t", mime]
            else:
                return b""
            proc = _run(argv)
            if proc.returncode != 0:
                return b""
            return proc.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return b""

    # ---------------------------------------------------------------- write

    def set_text(self, text: str) -> None:
        self.set_bytes(text.encode("utf-8"), "text/plain;charset=utf-8")

    def set_bytes(self, data: bytes, mime: str) -> None:
        # wl-copy and xclip fork a helper that keeps owning the selection.
        # Detach it from our stdio so it never holds the caller's pipes open.
        if self._backend == "wayland":
            subprocess.run(
                ["wl-copy", "--type", mime, "--"],
                input=data,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if self._backend == "x11":
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-i", "-t", mime],
                input=data,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        raise ClipboardError("no clipboard backend available")


class Watcher:
    """Notifies on clipboard changes, using the best mechanism available.

    There is no single cross-desktop way to observe the clipboard:

    - **X11 / XWayland** (GNOME on Wayland included) — GTK's ``owner-change``
      signal, which is backed by XFixes. Event-driven, instant, and it also
      sees copies made by Wayland-native apps because the compositor mirrors
      the selection to XWayland.
    - **wlroots compositors** (Sway, Hyprland) — ``wl-paste --watch``, which
      needs the data-control protocol. GNOME does *not* implement it, so
      this is only a fallback.
    - **Anything else** — a light polling thread that compares a cheap
      content signature.

    ``wl-paste --watch`` is tried only after a check, because on GNOME it
    exits immediately with an "unsupported protocol" error.
    """

    def __init__(
        self,
        clipboard: Clipboard,
        on_change: Callable[[], None],
        notify_argv: Optional[list[str]] = None,
        poll_interval: float = 0.45,
    ) -> None:
        self.clipboard = clipboard
        self.on_change = on_change
        self.notify_argv = notify_argv or []
        self.poll_interval = poll_interval
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last = ""
        self._gtk_clipboard = None
        self._handler_id = 0

    # ---------------------------------------------------------------- start

    def start(self) -> None:
        if self._start_owner_change():
            return
        if self.clipboard.backend == "wayland" and self._start_wl_paste_watch():
            return
        self._start_poll()

    def _start_owner_change(self) -> bool:
        """Watch the X11 selection via GTK/XFixes, when an X display exists."""
        if not os.environ.get("DISPLAY"):
            return False
        try:
            from .gtk_ui import Gdk, Gtk

            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        except Exception:
            return False
        if clipboard is None:
            return False
        self._gtk_clipboard = clipboard
        self._handler_id = clipboard.connect("owner-change", self._on_owner_change)
        return True

    def _on_owner_change(self, _clipboard, _event) -> None:
        self._fire()

    def _start_wl_paste_watch(self) -> bool:
        """Use ``wl-paste --watch`` when the compositor supports it."""
        if not shutil.which("wl-paste"):
            return False
        try:
            proc = subprocess.Popen(
                ["wl-paste", "--watch", *self.notify_argv],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        # It exits straight away when data-control is missing (GNOME).
        time.sleep(0.4)
        if proc.poll() is not None:
            return False
        self._proc = proc
        return True

    def _start_poll(self) -> None:
        self._last = self.clipboard.signature() + self._text_digest()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _text_digest(self) -> str:
        return str(hash(self.clipboard.get_text()))

    def _poll(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                signature = self.clipboard.signature() + self._text_digest()
            except Exception:
                continue
            if signature != self._last:
                self._last = signature
                self._fire()

    def _fire(self) -> None:
        try:
            self.on_change()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._gtk_clipboard is not None and self._handler_id:
            try:
                self._gtk_clipboard.disconnect(self._handler_id)
            except Exception:
                pass
            self._gtk_clipboard = None
            self._handler_id = 0
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc = None


def read_with_retry(clipboard: Clipboard, attempts: int = 4, delay: float = 0.06) -> Optional[dict]:
    """Read the clipboard, retrying briefly to win races with the source app."""
    for _ in range(max(1, attempts)):
        payload = clipboard.read()
        if payload:
            if payload["kind"] == "image" or payload.get("text"):
                return payload
        time.sleep(delay)
    return None
