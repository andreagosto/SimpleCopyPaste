"""The global shortcut that opens the panel.

It is a GNOME custom keybinding, so the value lives in gsettings in GTK's
accelerator syntax (``<Super><Alt>v``). The helpers here turn a key press
into that syntax and back into something readable, and are kept free of any
widget so they can be tested without a display.
"""

from __future__ import annotations

# Modifier tokens. GNOME has no canonical order (its own defaults include both
# "<Super><Control>" and "<Primary><Super>"), so this one is chosen to match
# the app's default and to read naturally: Super first, then Ctrl, Shift, Alt.
MODIFIERS = [
    ("<Super>", "Super"),
    ("<Primary>", "Ctrl"),
    ("<Shift>", "Shift"),
    ("<Alt>", "Alt"),
]

# Names of bare modifier keys: pressing one alone cannot be a shortcut.
BARE_MODIFIERS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "Hyper_L", "Hyper_R",
    "ISO_Level3_Shift", "Caps_Lock", "Num_Lock",
}


def from_event(keyval: int, state: int) -> str | None:
    """Build a GNOME accelerator from a key press, or None if unsuitable.

    At least one modifier is required: a global shortcut bound to a bare key
    would swallow that key everywhere.
    """
    from .gtk_ui import Gdk

    name = Gdk.keyval_name(keyval)
    if not name or name in BARE_MODIFIERS:
        return None

    parts: list[str] = []
    if state & Gdk.ModifierType.SUPER_MASK:
        parts.append("<Super>")
    if state & Gdk.ModifierType.CONTROL_MASK:
        parts.append("<Primary>")
    if state & Gdk.ModifierType.SHIFT_MASK:
        parts.append("<Shift>")
    if state & Gdk.ModifierType.MOD1_MASK:
        parts.append("<Alt>")
    if not parts:
        return None

    key = name.lower() if len(name) == 1 else name
    return "".join(parts) + key


def pretty(accelerator: str) -> str:
    """Render an accelerator for people: '<Super><Alt>v' -> 'Super+Alt+V'."""
    if not accelerator:
        return ""
    text = accelerator
    modifiers = ""
    for token, label in MODIFIERS:
        if token in text:
            text = text.replace(token, "")
            modifiers += label + "+"
    if len(text) == 1:
        text = text.upper()
    return modifiers + text


def is_valid(accelerator: str) -> bool:
    """Whether an accelerator is usable: a modifier plus a key."""
    if not accelerator:
        return False
    key = accelerator
    for token, _ in MODIFIERS:
        key = key.replace(token, "")
    has_modifier = any(token in accelerator for token, _ in MODIFIERS)
    return has_modifier and bool(key)
