"""Deciding whether a click reported by the shell should close a window.

Pure logic, testable without a display: the window plumbing only feeds these
numbers in.
"""

from __future__ import annotations

from simpleclips.clickaway import (
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
