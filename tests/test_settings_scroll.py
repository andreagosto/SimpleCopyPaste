"""Number fields must not change on an accidental wheel scroll."""

from __future__ import annotations

from simpleclips.gtk_ui import Gdk, Gtk


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

    from simpleclips.settings import SettingsWindow

    return SettingsWindow(App())


def test_wheel_is_ignored_when_the_field_is_not_focused():
    window = make_settings()
    assert window._on_spin_scroll(FakeSpin(focused=False), None) is True


def test_wheel_works_when_the_field_is_focused():
    window = make_settings()
    assert window._on_spin_scroll(FakeSpin(focused=True), None) is False


def test_every_number_field_ignores_the_wheel():
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
    from simpleclips.gtk_ui import any_popup_open

    assert any_popup_open([FakeCombo(False), FakeCombo(True)]) is True


def test_no_popup_when_every_dropdown_is_closed():
    from simpleclips.gtk_ui import any_popup_open

    assert any_popup_open([FakeCombo(False), FakeCombo(False)]) is False


def test_no_popup_with_no_combos():
    from simpleclips.gtk_ui import any_popup_open

    assert any_popup_open([]) is False


def test_settings_registers_its_dropdowns():
    window = make_settings()
    assert window._choice_boxes, "the shortcut dropdown must be tracked"
    assert any(hasattr(c, "get_property") for c in window._choice_boxes)
