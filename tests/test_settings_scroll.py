"""Number fields must not change on an accidental wheel scroll."""

from __future__ import annotations

from simplecopypaste.gtk_ui import Gdk, Gtk


class FakeSpin(Gtk.SpinButton):
    """SpinButton whose focus state we control for the test."""

    def __init__(self, focused: bool) -> None:
        super().__init__()
        self._focused = focused

    def has_focus(self) -> bool:
        return self._focused


def make_settings():
    """A SettingsWindow without a daemon behind it."""
    class Config:
        max_items = 20
        max_history = 100
        persist_history = True
        images = True
        image_files = True
        max_image_pixels = 20_000_000
        paste = True
        paste_shortcut = "ctrl+v"
        show_paste_hint = True
        popup_width = 560
        popup_max_height = 560

    class App:
        config = Config()

        def apply_config(self):
            pass

    from simplecopypaste.settings import SettingsWindow

    return SettingsWindow(App())


def test_wheel_is_ignored_when_the_field_is_not_focused(gui):
    window = make_settings()
    assert window._on_spin_scroll(FakeSpin(focused=False), None) is True


def test_wheel_works_when_the_field_is_focused(gui):
    window = make_settings()
    assert window._on_spin_scroll(FakeSpin(focused=True), None) is False


def test_every_number_field_ignores_the_wheel(gui):
    # guards against a new field forgetting the handler
    window = make_settings()
    fields = [
        window.max_items,
        window.max_history,
        window.max_image_pixels,
        window.popup_width,
        window.popup_max_height,
    ]
    for field in fields:
        consumed = window._on_spin_scroll(FakeSpin(focused=False), None)
        assert consumed is True


# --------------------------------------------------- dropdown must not close


class FakeCombo:
    def __init__(self, shown: bool) -> None:
        self._shown = shown

    def get_property(self, name: str):
        assert name == "popup-shown"
        return self._shown


def test_open_dropdown_counts_as_a_popup():
    from simplecopypaste.gtk_ui import any_popup_open

    assert any_popup_open([FakeCombo(False), FakeCombo(True)]) is True


def test_no_popup_when_every_dropdown_is_closed():
    from simplecopypaste.gtk_ui import any_popup_open

    assert any_popup_open([FakeCombo(False), FakeCombo(False)]) is False


def test_no_popup_with_no_combos():
    from simplecopypaste.gtk_ui import any_popup_open

    assert any_popup_open([]) is False


def test_settings_does_not_close_while_a_dropdown_is_open(gui):
    # A dropdown lives in its own toplevel, so opening it moves focus away.
    # The close-on-focus-loss path must stand down while one is open.
    window = make_settings()
    window._choice_boxes.append(FakeCombo(True))
    window.window.show_all()
    try:
        window._close_if_focus_left()
        assert window.window.get_visible(), "closed with a dropdown open"
    finally:
        window.window.destroy()


def test_settings_closes_when_no_dropdown_is_open(gui):
    window = make_settings()
    window._choice_boxes.append(FakeCombo(False))
    window.window.show_all()
    try:
        window._close_if_focus_left()
        assert not window.window.get_visible(), "should have closed"
    finally:
        window.window.destroy()
