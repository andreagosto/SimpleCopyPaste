"""Payload de-duplication and watcher selection."""

from __future__ import annotations

from simpleclips.clipboard import Clipboard, Watcher
from simpleclips.daemon import _payload_signature


def test_text_signature_is_the_text():
    assert _payload_signature({"kind": "text", "text": "hello"}) == "text:hello"


def test_empty_text_has_no_signature():
    assert _payload_signature({"kind": "text", "text": ""}) is None


def test_image_signature_is_the_content_hash():
    payload = {"kind": "image", "data": b"\x89PNG...", "mime": "image/png"}
    assert _payload_signature(payload) == _payload_signature(dict(payload))
    other = {"kind": "image", "data": b"\x89PNG...different", "mime": "image/png"}
    assert _payload_signature(payload) != _payload_signature(other)


def test_watcher_falls_back_to_poll_without_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    watcher = Watcher(Clipboard(), lambda: None)
    started = {"poll": False}
    monkeypatch.setattr(watcher, "_start_poll", lambda: started.__setitem__("poll", True))
    monkeypatch.setattr(watcher, "_start_wl_paste_watch", lambda: False)
    watcher.start()
    assert started["poll"] is True


def test_watcher_prefers_owner_change_when_a_display_exists(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    watcher = Watcher(Clipboard(), lambda: None)
    calls = []
    monkeypatch.setattr(watcher, "_start_owner_change", lambda: True)
    monkeypatch.setattr(watcher, "_start_poll", lambda: calls.append("poll"))
    monkeypatch.setattr(watcher, "_start_wl_paste_watch", lambda: calls.append("watch"))
    watcher.start()
    assert calls == []  # owner-change won, nothing else started
