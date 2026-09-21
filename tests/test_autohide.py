"""Auto-hide on focus loss, and the guard against an instant reopen.

The decision is a small pure function so it can be tested without a display:
windows cannot be created in CI, but the logic that decides *when* to close
can still be checked.
"""

from __future__ import annotations

from simpleclips.gtk_ui import FOCUS_OUT_GRACE, should_autohide
from simpleclips.popup import REOPEN_GUARD, within_reopen_guard


# --------------------------------------------------------------- autohide


def test_hides_once_the_grace_period_has_passed():
    assert should_autohide(visible=True, shown_at=100.0, now=100.5) is True


def test_ignores_focus_loss_right_after_opening():
    # showing a window briefly moves focus around; closing instantly would
    # make the window disappear the moment it appears
    assert should_autohide(visible=True, shown_at=100.0, now=100.1) is False
    assert should_autohide(visible=True, shown_at=100.0, now=100.0) is False


def test_does_nothing_when_already_hidden():
    assert should_autohide(visible=False, shown_at=0.0, now=999.0) is False


def test_boundary_is_exclusive():
    exactly = FOCUS_OUT_GRACE
    assert should_autohide(visible=True, shown_at=0.0, now=exactly) is False
    assert should_autohide(visible=True, shown_at=0.0, now=exactly + 0.01) is True


# ----------------------------------------------------------- reopen guard


def test_no_guard_before_any_hide():
    assert within_reopen_guard(hidden_at=0.0, now=1000.0) is False


def test_guards_right_after_a_focus_out_hide():
    # the click that stole focus also fires a toggle a moment later; it must
    # not bring the popup straight back
    assert within_reopen_guard(hidden_at=100.0, now=100.2) is True


def test_guard_expires():
    assert within_reopen_guard(hidden_at=100.0, now=100.0 + REOPEN_GUARD + 0.05) is False
    assert within_reopen_guard(hidden_at=100.0, now=100.0 + REOPEN_GUARD - 0.05) is True
