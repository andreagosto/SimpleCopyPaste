"""A small settings window covering every option in Config."""

from __future__ import annotations

import os
import subprocess
import time

from .gtk_ui import Gdk, Gtk, set_app_icon, should_autohide
from .clickaway import ClickAway, should_close_on_click
from . import input_inject

MP = 1_000_000

# Combos the GNOME extension and the tool backends all understand.
PASTE_SHORTCUTS = [
    ("ctrl+v", "Ctrl+V"),
    ("ctrl+shift+v", "Ctrl+Shift+V"),
    ("shift+insert", "Shift+Insert"),
]

# Keeps settings hints from widening the window: they wrap within this box.
HINT_WIDTH = 300
HINT_MAX_CHARS = 42


class SettingsWindow:
    """Live-editing UI for the config file.

    Changes are applied and saved as soon as they are made, so there is no
    OK/Cancel: closing the window keeps whatever is on screen.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.window: Gtk.Window | None = None
        self._loading = False
        self._shown_at = 0.0
        self._internal_click_at = 0.0
        self.click_away = ClickAway(self._on_global_click)
        self._build()

    # ---------------------------------------------------------------- build

    def _build(self) -> None:
        set_app_icon()
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("SimpleClips Settings")
        self.window.set_resizable(False)
        # A dialog, not an app window: it closes on click-away, so a minimise
        # button would only be a control that does nothing. Declaring it as
        # not belonging to the taskbar is what drops that button.
        self.window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.get_style_context().add_class("sc-settings")
        self.window.connect("key-press-event", self._on_key)
        self.window.connect("delete-event", self._on_delete)
        self.window.connect("focus-out-event", self._on_focus_out)
        self.window.connect("button-press-event", self._remember_internal_click)

        self._load_css()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer)

        heading = Gtk.Label(label="Settings", xalign=0.0)
        heading.get_style_context().add_class("sc-settings-title")
        outer.pack_start(heading, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.pack_start(self.body, True, True, 0)

        config = self.app.config
        self._loading = True

        self._section("History")
        self.max_items = self._row_int(
            "Entries shown",
            "How many clips the popup lists.",
            config.max_items, 1, 100, 1,
            lambda v: setattr(config, "max_items", v),
        )
        self.max_history = self._row_int(
            "History kept",
            "Unpinned clips beyond this are discarded.",
            config.max_history, 5, 1000, 5,
            lambda v: setattr(config, "max_history", v),
        )
        self.persist_history = self._row_bool(
            "Keep across sessions",
            "Off: unpinned clips are cleared at every restart.",
            config.persist_history,
            lambda v: setattr(config, "persist_history", v),
        )

        self._section("Clipboard")
        self.images = self._row_bool(
            "Store images",
            "Keep copied pictures and screenshots.",
            config.images,
            self._on_images_toggled,
        )
        self.image_files = self._row_bool(
            "Open image files",
            "When you copy an image file, store the picture instead of its path.",
            config.image_files,
            lambda v: setattr(config, "image_files", v),
        )
        self.max_image_pixels = self._row_int(
            "Max image size",
            "Bigger images are skipped.\n20 MP covers screenshots up to two 4K screens.",
            config.max_image_pixels // MP, 1, 300, 1,
            lambda v: setattr(config, "max_image_pixels", v * MP),
            unit="MP",
        )
        self.paste = self._row_bool(
            "Paste automatically",
            "Press the paste shortcut for you after choosing a clip.",
            config.paste,
            lambda v: setattr(config, "paste", v),
        )
        self.paste_row = self.paste.get_parent()
        self.paste_shortcut = self._row_choice(
            "Paste shortcut",
            "Terminals need Ctrl+Shift+V; most other apps use Ctrl+V.",
            PASTE_SHORTCUTS,
            config.paste_shortcut,
            lambda value: setattr(config, "paste_shortcut", value),
        )
        self.show_paste_hint = self._row_bool(
            "Show auto-paste hint",
            "Discreet tip when automatic pasting is unavailable.",
            config.show_paste_hint,
            lambda v: setattr(config, "show_paste_hint", v),
        )

        self._section("Appearance")
        self.popup_width = self._row_int(
            "Popup width",
            "Width of the clip panel.",
            config.popup_width, 320, 1000, 10,
            lambda v: setattr(config, "popup_width", v),
            unit="px",
        )
        self.popup_max_height = self._row_int(
            "Popup max height",
            "The list scrolls beyond this height.",
            config.popup_max_height, 160, 1400, 20,
            lambda v: setattr(config, "popup_max_height", v),
            unit="px",
        )

        self._loading = False

        status = self._status_label()
        self.status = status
        outer.pack_start(status, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.get_style_context().add_class("sc-settings-actions")
        clear = self._button("Clear unpinned history")
        clear.connect("clicked", self._on_clear)
        actions.pack_start(clear, False, False, 0)
        open_cfg = self._button("Open config file")
        open_cfg.connect("clicked", self._on_open_config)
        actions.pack_start(open_cfg, False, False, 0)
        outer.pack_start(actions, False, False, 0)

        close = self._button("Close", primary=True)
        close.connect("clicked", lambda _b: self.hide())
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        footer.get_style_context().add_class("sc-settings-footer")
        footer.pack_end(close, False, False, 0)
        outer.pack_start(footer, False, False, 0)

    def _load_css(self) -> None:
        path = os.path.join(os.path.dirname(__file__), "style.css")
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(path)
        except Exception:
            return
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _section(self, title: str) -> None:
        label = Gtk.Label(label=title, xalign=0.0)
        label.get_style_context().add_class("sc-settings-section")
        self.body.pack_start(label, False, False, 0)

    def _row(self, title: str, hint: str, control: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.get_style_context().add_class("sc-settings-row")

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text.set_hexpand(True)
        name = Gtk.Label(label=title, xalign=0.0)
        name.get_style_context().add_class("sc-settings-name")
        text.pack_start(name, False, False, 0)
        sub = None
        if hint:
            sub = Gtk.Label(label=hint, xalign=0.0)
            sub.get_style_context().add_class("sc-settings-hint")
            sub.set_line_wrap(True)
            # Cap the width so a long hint wraps instead of stretching the
            # whole window; the label still grows taller as needed.
            sub.set_max_width_chars(HINT_MAX_CHARS)
            sub.set_size_request(HINT_WIDTH, -1)
            text.pack_start(sub, False, False, 0)
        row.pack_start(text, True, True, 0)

        control.set_valign(Gtk.Align.CENTER)
        row.pack_start(control, False, False, 0)
        self.body.pack_start(row, False, False, 0)
        row.hint_label = sub
        row.control = control
        return row

    def _row_int(
        self,
        title: str,
        hint: str,
        value: int,
        lower: int,
        upper: int,
        step: int,
        apply,
        unit: str = "",
    ) -> Gtk.SpinButton:
        spin = Gtk.SpinButton.new_with_range(lower, upper, step)
        spin.set_value(value)
        spin.set_numeric(True)

        def on_change(widget):
            if self._loading:
                return
            apply(int(widget.get_value()))
            self._save()

        spin.connect("value-changed", on_change)
        # A SpinButton scrolls its value on wheel events, which makes it very
        # easy to change a setting by accident while scrolling the window.
        # Ignore the wheel unless the field has focus, so it must be a
        # deliberate gesture.
        spin.connect("scroll-event", self._on_spin_scroll)

        if unit:
            control = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            control.pack_start(spin, False, False, 0)
            label = Gtk.Label(label=unit)
            label.get_style_context().add_class("sc-settings-unit")
            control.pack_start(label, False, False, 0)
            self._row(title, hint, control)
        else:
            self._row(title, hint, spin)
        return spin

    def _on_spin_scroll(self, widget, _event) -> bool:
        """Swallow wheel events on number fields unless they are focused."""
        return not widget.has_focus()

    def _row_bool(self, title: str, hint: str, value: bool, apply) -> Gtk.Switch:
        switch = Gtk.Switch()
        switch.set_active(value)

        def on_change(widget, _state):
            if self._loading:
                return False
            apply(bool(widget.get_active()))
            self._save()
            return False

        switch.connect("state-set", on_change)
        self._row(title, hint, switch)
        return switch

    def _row_choice(
        self,
        title: str,
        hint: str,
        options: list[tuple[str, str]],
        value: str,
        apply,
    ) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        for key, label in options:
            combo.append(key, label)
        combo.set_active_id(value)
        if combo.get_active_id() is None and options:
            combo.set_active(0)

        def on_change(widget):
            if self._loading:
                return
            chosen = widget.get_active_id()
            if chosen is not None:
                apply(chosen)
                self._save()

        combo.connect("changed", on_change)
        self._row(title, hint, combo)
        return combo

    def _row_choice_set(self, combo: Gtk.ComboBoxText, value: str) -> None:
        if combo.get_active_id() != value:
            combo.set_active_id(value)
            if combo.get_active_id() is None:
                combo.set_active(0)

    def _button(self, label: str, primary: bool = False) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.get_style_context().add_class("sc-btn")
        if primary:
            button.get_style_context().add_class("sc-btn-primary")
        return button

    def _status_label(self) -> Gtk.Label:
        label = Gtk.Label(xalign=0.0)
        label.get_style_context().add_class("sc-settings-status")
        label.set_no_show_all(True)
        return label

    # -------------------------------------------------------------- actions

    def _save(self) -> None:
        try:
            self.app.apply_config()
        except Exception:
            pass
        if self.status is not None:
            self.status.set_text("Saved")
            self.status.show()

    def _on_clear(self, _button) -> None:
        self.app.store.clear_unpinned()
        if self.app.popup.visible:
            self.app.popup.refresh()
        if self.status is not None:
            self.status.set_text("Unpinned history cleared")
            self.status.show()

    def _on_open_config(self, _button) -> None:
        from . import config as config_mod

        path = config_mod.config_file()
        try:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    # -------------------------------------------------------------- control

    def show(self) -> None:
        self._load_values()
        assert self.window is not None
        self.window.show_all()
        if self.status is not None:
            self.status.hide()
        self.window.present()
        self._shown_at = time.time()
        # Clicks on the desktop do not move focus, so focus-out alone is not
        # enough to notice them.
        self.click_away.start()

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()
        self.click_away.stop()

    def toggle(self) -> None:
        if self.window is not None and self.window.get_visible():
            self.hide()
        else:
            self.show()

    def _load_values(self) -> None:
        config = self.app.config
        self._loading = True
        self.max_items.set_value(config.max_items)
        self.max_history.set_value(config.max_history)
        self.persist_history.set_active(config.persist_history)
        self.images.set_active(config.images)
        self.image_files.set_active(config.image_files)
        self.max_image_pixels.set_value(config.max_image_pixels // MP)
        self.paste.set_active(config.paste)
        self._row_choice_set(self.paste_shortcut, config.paste_shortcut)
        self.show_paste_hint.set_active(config.show_paste_hint)
        self.popup_width.set_value(config.popup_width)
        self.popup_max_height.set_value(config.popup_max_height)
        self._loading = False
        self._refresh_paste_availability()
        self._refresh_images_availability()

    def _refresh_images_availability(self) -> None:
        """Image sub-options only make sense while images are stored."""
        enabled = self.images.get_active()
        self.image_files.set_sensitive(enabled)
        self.max_image_pixels.set_sensitive(enabled)

    def _on_images_toggled(self, value: bool) -> None:
        self.app.config.images = value
        self._refresh_images_availability()

    def _refresh_paste_availability(self) -> None:
        """Reflect whether automatic pasting can work right now."""
        combo = self.app.config.paste_shortcut
        backend = input_inject.detect(combo)
        available = backend != "none"
        self.paste.set_sensitive(True)  # the preference itself is always settable
        self.show_paste_hint.set_sensitive(available)
        hint = self.paste_row.hint_label
        if hint is None:
            return
        if available:
            hint.set_text(f"Ready ({backend}).")
        elif os.environ.get("WAYLAND_DISPLAY"):
            hint.set_text(input_inject.extension_hint())
        else:
            command = input_inject.install_hint()
            detail = f" Install it with:  {command}." if command else ""
            hint.set_text(f"Unavailable: no input backend found.{detail}")

    def _on_key(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_delete(self, _widget, _event) -> bool:
        self.hide()
        return True

    def _on_focus_out(self, _widget, _event) -> bool:
        """Close when the click lands outside: focus moves to whatever was
        clicked, so losing focus is the signal we want."""
        if self.window is not None and should_autohide(
            self.window.get_visible(), self._shown_at, time.time()
        ):
            self.hide()
        return False

    def _on_global_click(self) -> None:
        """A click the shell saw: on the desktop or the top bar, not on us."""
        if self.window is None:
            return
        if should_close_on_click(
            self.window.get_visible(),
            self._shown_at,
            self._internal_click_at,
            time.time(),
        ):
            self.hide()

    def _remember_internal_click(self, _widget, _event) -> bool:
        """A press landed on this window, so click-away must not fire."""
        self._internal_click_at = time.time()
        return False
