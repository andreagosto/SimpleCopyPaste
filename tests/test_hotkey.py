"""Turning key presses into the accelerator GNOME stores, and back again."""

from __future__ import annotations

from simplecopypaste import hotkey
from simplecopypaste.gtk_ui import Gdk


def test_super_alt_v():
    accel = hotkey.from_event(Gdk.KEY_v, Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD1_MASK)
    assert accel == "<Super><Alt>v"


def test_control_becomes_primary():
    # GNOME writes Ctrl as <Primary>
    assert hotkey.from_event(Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK) == "<Primary>v"


def test_all_four_modifiers_in_a_stable_order():
    state = (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD1_MASK
             | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)
    assert hotkey.from_event(Gdk.KEY_F9, state) == "<Super><Primary><Shift><Alt>F9"


def test_bare_key_is_rejected():
    # a global shortcut on a bare key would swallow it everywhere
    assert hotkey.from_event(Gdk.KEY_v, 0) is None


def test_bare_modifier_is_rejected():
    for key in (Gdk.KEY_Control_L, Gdk.KEY_Shift_L, Gdk.KEY_Alt_L, Gdk.KEY_Super_L):
        assert hotkey.from_event(key, Gdk.ModifierType.SUPER_MASK) is None


def test_function_key_keeps_its_name():
    accel = hotkey.from_event(Gdk.KEY_F9, Gdk.ModifierType.SUPER_MASK)
    assert accel == "<Super>F9"


def test_pretty_renders_for_people():
    assert hotkey.pretty("<Super><Alt>v") == "Super+Alt+V"
    assert hotkey.pretty("<Primary><Shift>v") == "Ctrl+Shift+V"
    assert hotkey.pretty("<Super>F9") == "Super+F9"


def test_pretty_of_empty_is_empty():
    assert hotkey.pretty("") == ""


def test_validity():
    assert hotkey.is_valid("<Super><Alt>v") is True
    assert hotkey.is_valid("<Primary>F9") is True
    assert hotkey.is_valid("v") is False
    assert hotkey.is_valid("<Super>") is False
    assert hotkey.is_valid("") is False


def test_round_trip_through_the_settings_format():
    for accel in ("<Super><Alt>v", "<Primary><Shift>v", "<Super>F9"):
        assert hotkey.is_valid(accel)
        assert hotkey.pretty(accel) != accel


# ------------------------------------------- the keybinding API stays safe


def test_set_keybinding_refuses_an_empty_value(monkeypatch):
    # A bad write would leave the app unreachable: no shortcut to reopen it.
    from simplecopypaste import install

    called = []
    monkeypatch.setattr(install, "shutil", install.shutil)
    monkeypatch.setattr(install, "_gsettings_set", lambda *a: called.append(a) or True)
    assert install.set_keybinding("") is False
    assert install.set_keybinding("v") is False
    assert install.set_keybinding("<Super>") is False
    assert called == [], "nothing should have been written"


def test_current_keybinding_falls_back_to_the_default(monkeypatch):
    from simplecopypaste import install

    monkeypatch.setattr(install, "_gsettings_get", lambda *a: "''")
    assert install.current_keybinding() == install.DEFAULT_HOTKEY


def test_current_keybinding_returns_a_valid_stored_value(monkeypatch):
    from simplecopypaste import install

    monkeypatch.setattr(install, "_gsettings_get", lambda *a: "'<Primary><Shift>v'")
    assert install.current_keybinding() == "<Primary><Shift>v"
