"""The long-running daemon: owns history, watches the clipboard, serves IPC."""

from __future__ import annotations

import hashlib
import logging
import shutil
import signal
import sys
import threading

from .gtk_ui import GLib, Gtk

from . import config as config_mod
from . import input_inject, ipc, images, notifications
from .clipboard import Clipboard, Watcher, read_with_retry
from .popup import Popup
from .settings import SettingsWindow
from .store import IMAGE, Clip, Store

log = logging.getLogger("simpleclips")


def _size(num_bytes: int) -> str:
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        value = num_bytes / (1024 * 1024)
        return f"{value:.1f}".rstrip("0").rstrip(".") + " MB"
    value = num_bytes / (1024 * 1024 * 1024)
    return f"{value:.1f}".rstrip("0").rstrip(".") + " GB"


def _mp(pixels: int) -> str:
    value = pixels / 1_000_000
    return f"{value:.0f} MP" if value >= 10 else f"{value:.1f} MP"


def _payload_signature(payload: dict) -> str | None:
    """Cheap identity of a clipboard payload, for change de-duplication."""
    if payload["kind"] == "image":
        return "image:" + hashlib.sha256(payload["data"]).hexdigest()
    text = payload.get("text", "")
    return "text:" + text if text else None


def _notify_argv() -> list[str]:
    script = shutil.which("simpleclips")
    if script:
        return [script, "_notify"]
    return [sys.executable, "-m", "simpleclips", "_notify"]


class Daemon:
    def __init__(self) -> None:
        self.config = config_mod.Config.load()
        self.store = Store()
        self.clipboard = Clipboard()
        self.clipboard.resolve_image_files = self.config.image_files
        self.paste_backend = input_inject.detect(self.config.paste_shortcut)
        self.active_key = ""
        self.notice = ""
        self.notice_detail = ""
        self._last_signature: str | None = None
        self.popup = Popup(self)
        self.settings = SettingsWindow(self)
        self.server = ipc.Server(self._handle)
        self.watcher = Watcher(
            self.clipboard, self._on_clipboard_change, notify_argv=_notify_argv()
        )

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        config_mod.data_dir().mkdir(parents=True, exist_ok=True)
        self.server.start()
        if not self.config.persist_history:
            # Volatile mode: only pinned clips survive a session restart.
            self.store.clear_unpinned()
        payload = self.clipboard.read()
        if payload:
            self._store_payload(payload)
        self.watcher.start()
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        log.info(
            "started: clipboard=%s paste=%s clips=%d images=%s",
            self.clipboard.backend,
            self.paste_backend,
            len(self.store.clips),
            self.config.images,
        )

    def run(self) -> int:
        self.start()
        Gtk.main()
        return 0

    def quit(self) -> None:
        try:
            self.watcher.stop()
            self.server.stop()
        finally:
            self.store.save()
            Gtk.main_quit()

    def _on_signal(self, _signum, _frame) -> None:
        GLib.idle_add(self._quit_idle)

    def _quit_idle(self) -> bool:
        self.quit()
        return False

    # ----------------------------------------------------------- clipboard

    def _on_clipboard_change(self) -> None:
        GLib.idle_add(self._record_current)

    def _record_current(self) -> bool:
        payload = read_with_retry(self.clipboard)
        if payload:
            self._store_payload(payload)
        return False

    def sync_clipboard(self) -> None:
        """Re-read the clipboard without refreshing the popup (used on show)."""
        payload = self.clipboard.read()
        if payload:
            self._store_payload(payload, refresh_popup=False)

    def _store_payload(self, payload: dict, refresh_popup: bool = True) -> None:
        # The watcher can hand us the same content more than once (it fires
        # once for the pre-existing selection on start, and sync_clipboard
        # runs on every open), so ignore a repeat outright instead of
        # re-saving it and bumping its counter.
        signature = _payload_signature(payload)
        if signature is not None and signature == self._last_signature:
            return
        self._last_signature = signature

        if payload["kind"] == "image":
            clip = self._store_image(payload, refresh_popup)
        else:
            clip = self.store.add_text(payload["text"], self.config.max_history)
        if clip is None:
            return
        self.notice = ""
        self.active_key = clip.key
        if refresh_popup and self.popup.visible:
            self.popup.refresh()

    def _store_image(self, payload: dict, refresh_popup: bool) -> Clip | None:
        config = self.config
        if not config.images:
            self._warn(
                "Image not saved",
                "Storing images is turned off in SimpleClips settings.",
                refresh_popup,
            )
            return None

        data = payload["data"]
        if len(data) > config.max_image_bytes:
            self._warn(
                "Image too large, not saved",
                f"This image is {_size(len(data))}, above the "
                f"{_size(config.max_image_bytes)} safety limit.",
                refresh_popup,
            )
            return None

        size = images.dimensions(data)
        if size is None:
            self._warn(
                "Image not saved",
                "The copied image format could not be read.",
                refresh_popup,
            )
            return None

        width, height = size
        pixels = width * height
        if pixels > config.max_image_pixels:
            self._warn(
                "Image too large, not saved",
                f"This image is {width}\u00d7{height} ({_mp(pixels)}), above "
                f"the {_mp(config.max_image_pixels)} limit. Raise "
                "'Max image size' in SimpleClips settings to keep it.",
                refresh_popup,
            )
            return None

        return self.store.add_image(
            data, payload["mime"], config.max_history, payload.get("source", "")
        )

    def _warn(self, title: str, message: str, refresh_popup: bool) -> None:
        self.notice = title
        self.notice_detail = message
        notifications.send(title, message)
        if refresh_popup and self.popup.visible:
            self.popup.refresh()

    # -------------------------------------------------------------- choose

    def choose(self, clip: Clip) -> None:
        try:
            if clip.kind == IMAGE:
                data = images.read(clip.image)
                if data is None:
                    log.warning("image blob missing: %s", clip.image)
                else:
                    self.clipboard.set_bytes(data, clip.mime or "image/png")
            else:
                self.clipboard.set_text(clip.text)
        except Exception as exc:  # pragma: no cover - clipboard can be flaky
            log.warning("could not set clipboard: %s", exc)
        self.store.bump(clip)
        self.active_key = clip.key
        self.popup.hide()
        if self.config.paste and self.paste_backend != "none":
            GLib.timeout_add(240, self._do_paste)

    def _do_paste(self) -> bool:
        threading.Thread(
            target=input_inject.send_paste,
            args=(self.paste_backend,),
            kwargs={"combo": self.config.paste_shortcut, "delay": 0.05},
            daemon=True,
        ).start()
        return False

    # ----------------------------------------------------------------- ipc

    def _handle(self, request: dict) -> dict:
        cmd = request.get("cmd", "")
        if cmd == "ping":
            return {"ok": True, "app": "simpleclips"}
        if cmd == "status":
            return {
                "ok": True,
                "clipboard": self.clipboard.backend,
                "paste": self.paste_backend,
                "clips": len(self.store.clips),
                "images": sum(1 for c in self.store.clips if c.kind == IMAGE),
                "pinned": sum(1 for c in self.store.clips if c.pinned),
                "visible": self.popup.visible,
            }
        if cmd == "toggle":
            GLib.idle_add(self._idle_toggle)
            return {"ok": True}
        if cmd == "show":
            GLib.idle_add(self._idle_show)
            return {"ok": True}
        if cmd == "hide":
            GLib.idle_add(self._idle_hide)
            return {"ok": True}
        if cmd == "notify":
            self._on_clipboard_change()
            return {"ok": True}
        if cmd == "clear":
            GLib.idle_add(self._idle_clear)
            return {"ok": True}
        if cmd == "settings":
            GLib.idle_add(self._idle_settings)
            return {"ok": True}
        if cmd == "pick":
            return self._pick(request.get("index", 1))
        if cmd == "quit":
            GLib.idle_add(self._quit_idle)
            return {"ok": True}
        return {"ok": False, "error": f"unknown command: {cmd}"}

    def _idle_toggle(self) -> bool:
        self.popup.toggle()
        return False

    def _idle_show(self) -> bool:
        self.popup.show()
        return False

    def _idle_hide(self) -> bool:
        self.popup.hide()
        return False

    def _idle_clear(self) -> bool:
        self.store.clear_unpinned()
        if self.popup.visible:
            self.popup.refresh()
        return False

    def _idle_settings(self) -> bool:
        self.popup.hide()
        self.settings.toggle()
        return False

    def _pick(self, index) -> dict:
        """Copy the Nth clip (1-based, as shown by ``simpleclips list``)."""
        try:
            position = int(index)
        except (TypeError, ValueError):
            return {"ok": False, "error": "index must be a number"}
        clips = self.store.ordered()
        if not clips:
            return {"ok": False, "error": "no clips stored"}
        if position < 1 or position > len(clips):
            return {"ok": False, "error": f"index out of range (1-{len(clips)})"}
        self.choose(clips[position - 1])
        return {"ok": True, "kind": clips[position - 1].kind}

    # --------------------------------------------------------------- config

    def apply_config(self) -> None:
        """Persist the in-memory config and push it to live widgets."""
        self.config.save()
        self.paste_backend = input_inject.detect(self.config.paste_shortcut)
        self.clipboard.resolve_image_files = self.config.image_files
        self.popup.apply_config()
        if self.popup.visible:
            self.popup.refresh()


def run_daemon() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        return Daemon().run()
    except ipc.CommandError as exc:
        log.error("%s", exc)
        return 1
