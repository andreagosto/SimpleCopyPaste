"""Pointer source selection and fallback."""

from __future__ import annotations

from simpleclips import pointer
from simpleclips.pointer import Pointer


def test_prefers_gnome_shell_when_available(monkeypatch):
    p = Pointer()
    monkeypatch.setattr(p.extension, "available", lambda: True)
    monkeypatch.setattr(p.extension, "get_pointer", lambda: (3000, 700))
    monkeypatch.setattr(pointer, "x11_pointer", lambda: (1, 2))
    assert p.get() == (3000, 700, "gnome-shell")


def test_falls_back_to_x11_when_extension_says_nothing(monkeypatch):
    p = Pointer()
    monkeypatch.setattr(p.extension, "available", lambda: True)
    monkeypatch.setattr(p.extension, "get_pointer", lambda: None)
    monkeypatch.setattr(pointer, "x11_pointer", lambda: (10, 20))
    assert p.get() == (10, 20, "x11")


def test_skips_extension_call_when_unavailable(monkeypatch):
    p = Pointer()
    monkeypatch.setattr(p.extension, "available", lambda: False)
    monkeypatch.setattr(p.extension, "get_pointer", lambda: (1, 1))
    monkeypatch.setattr(pointer, "x11_pointer", lambda: (10, 20))
    assert p.get() == (10, 20, "x11")


def test_returns_none_when_nothing_available(monkeypatch):
    p = Pointer()
    monkeypatch.setattr(p.extension, "available", lambda: False)
    monkeypatch.setattr(pointer, "x11_pointer", lambda: None)
    assert p.get() is None
    assert p.source() == "none"


def test_source_reports_gnome_shell(monkeypatch):
    p = Pointer()
    monkeypatch.setattr(p.extension, "available", lambda: True)
    assert p.source() == "gnome-shell"
