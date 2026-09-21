"""Deciding whether a click reported by the shell should close a window.

Pure logic, testable without a display: the window plumbing only feeds these
numbers in.
"""

from __future__ import annotations

from simplecopypaste.clickaway import (
    CLICK_GRACE,
    INTERNAL_CLICK_WINDOW,
    should_close_on_click,
)


def test_closes_on_an_outside_click():
    assert should_close_on_click(
        visible=True, shown_at=100.0, last_internal_click=0.0, now=101.0
    ) is True


def test_never_closes_when_not_visible():
    assert should_close_on_click(
        visible=False, shown_at=100.0, last_internal_click=0.0, now=101.0
    ) is False


def test_ignores_the_click_that_opened_the_window():
    # the panel icon click can still be arriving while the popup opens
    assert should_close_on_click(
        visible=True, shown_at=100.0, last_internal_click=0.0, now=100.1
    ) is False


def test_ignores_a_click_the_window_handled_itself():
    # a press inside the window raises both an internal event and possibly a
    # report; the internal one must win
    assert should_close_on_click(
        visible=True, shown_at=100.0, last_internal_click=101.0, now=101.05
    ) is False


def test_closes_when_the_internal_click_is_old():
    assert should_close_on_click(
        visible=True,
        shown_at=100.0,
        last_internal_click=100.5,
        now=100.5 + INTERNAL_CLICK_WINDOW + 0.01,
    ) is True


def test_grace_boundary_is_exclusive():
    assert should_close_on_click(
        visible=True, shown_at=0.0, last_internal_click=0.0, now=CLICK_GRACE - 0.05
    ) is False
    assert should_close_on_click(
        visible=True, shown_at=0.0, last_internal_click=0.0, now=CLICK_GRACE + 0.05
    ) is True


def test_internal_boundary_is_exclusive():
    assert should_close_on_click(
        visible=True,
        shown_at=0.0,
        last_internal_click=1.0,
        now=1.0 + INTERNAL_CLICK_WINDOW,
    ) is True
    assert should_close_on_click(
        visible=True,
        shown_at=0.0,
        last_internal_click=1.0,
        now=1.0 + INTERNAL_CLICK_WINDOW - 0.01,
    ) is False


# ------------------------------------------------- subscription resilience


class FakeConnection:
    def __init__(self):
        self.subscribed = []

    def signal_subscribe(self, sender, iface, name, path, arg, flags, cb):
        self.subscribed.append(name)
        return len(self.subscribed)  # a non-zero id


def test_subscribes_to_both_signal_names(monkeypatch):
    # "Dismiss" is current; "Clicked" is what an extension loaded from an
    # earlier login still emits, and it must keep working until it reloads.
    from simplecopypaste import shell_ext

    shell = shell_ext.ShellExtension()
    conn = FakeConnection()
    monkeypatch.setattr(shell, "_conn", lambda: conn)
    monkeypatch.setattr(shell, "available", lambda: True)
    shell._endpoint = ("/org/simplecopypaste/Shell", "org.simplecopypaste.Shell")

    assert shell.subscribe_clicked(lambda: None) is True
    assert conn.subscribed == ["Dismiss", "Clicked"]


def test_subscribe_is_not_repeated(monkeypatch):
    from simplecopypaste import shell_ext

    shell = shell_ext.ShellExtension()
    conn = FakeConnection()
    monkeypatch.setattr(shell, "_conn", lambda: conn)
    monkeypatch.setattr(shell, "available", lambda: True)
    shell._endpoint = ("/org/simplecopypaste/Shell", "org.simplecopypaste.Shell")

    shell.subscribe_clicked(lambda: None)
    shell.subscribe_clicked(lambda: None)
    assert conn.subscribed == ["Dismiss", "Clicked"]
