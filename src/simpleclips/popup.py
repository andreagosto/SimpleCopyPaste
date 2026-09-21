"""The Win+V style popup: a frameless list of recent clips at the pointer."""

from __future__ import annotations

import os
import time

from .gtk_ui import Gdk, GLib, Gtk, Pango
from . import images, input_inject
from .pointer import Pointer
from .store import IMAGE, Clip

PREVIEW_CHARS = 400
TOOLTIP_CHARS = 2000
TOOLTIP_WIDTH = 72
POINTER_OFFSET = 14
THUMB_HEIGHT = 60


def _wrap_for_tooltip(text: str, width: int = TOOLTIP_WIDTH) -> str:
    """Hard-wrap text so it stays readable in a tooltip.

    Tooltips wrap on word boundaries by default, which lets a long URL or
    a base64 blob run off the side of the screen. Breaking the lines here
    keeps the result predictable whatever the tooltip does.
    """
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            if cut <= 0:
                cut = width
            lines.append(line[:cut])
            line = line[cut:]
            if line.startswith(" "):
                line = line[1:]
        lines.append(line)
    return "\n".join(lines)


def _tooltip_for(clip: Clip) -> str:
    """Full content of a clip for the row tooltip.

    Unlike the one-line preview this keeps the original line breaks, so
    multi-line clips (code, addresses) stay readable. Only a very large
    clip is capped, with a note saying so.
    """
    if clip.kind == IMAGE:
        lines = [f"Image {clip.width}\u00d7{clip.height}", clip.mime or "unknown type"]
        if clip.source:
            lines.insert(0, os.path.basename(clip.source))
        return _wrap_for_tooltip("\n".join(lines))
    text = clip.text
    if len(text) > TOOLTIP_CHARS:
        text = text[:TOOLTIP_CHARS].rstrip() + "\n\u2026 (preview truncated)"
    return _wrap_for_tooltip(text)


def compute_position(
    pointer_x: int,
    pointer_y: int,
    width: int,
    height: int,
    area: tuple[int, int, int, int],
    offset: int = POINTER_OFFSET,
) -> tuple[int, int]:
    """Where to put a ``width`` x ``height`` popup for a cursor at (x, y).

    The popup opens just below-right of the cursor. When it would not fit,
    it *flips* to the other side of the cursor (above / left) instead of
    being shoved into the screen corner, then is clamped only as a last
    resort. ``area`` is the monitor workarea as (x, y, width, height).
    """
    ax, ay, aw, ah = area

    x = pointer_x + offset
    if x + width > ax + aw:
        x = pointer_x - width - offset
    x = max(ax, min(x, ax + aw - width))

    y = pointer_y + offset
    if y + height > ay + ah:
        y = pointer_y - height - offset
    y = max(ay, min(y, ay + ah - height))

    return int(x), int(y)


def _format_age(created: float) -> str:
    delta = max(0.0, time.time() - created)
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def _preview(text: str) -> str:
    collapsed = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " \u21b5 ")
    collapsed = " ".join(collapsed.split())
    if len(collapsed) > PREVIEW_CHARS:
        collapsed = collapsed[:PREVIEW_CHARS].rstrip() + "\u2026"
    return collapsed


def _human_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.0f} KB"
    return f"{num / (1024 * 1024):.1f} MB"


def _on_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return "gnome" in desktop or "ubuntu" in desktop


class PinIcon(Gtk.DrawingArea):
    """A classic push-pin drawn with Cairo.

    Drawing it ourselves (instead of using a font glyph) keeps it crisp at
    any scale and lets CSS drive the color through the normal ``color``
    property and its ``:hover`` / ``.on`` states.
    """

    # Material "push_pin" outline, in a 24x24 box.
    PATH = [
        (16, 12), (16, 4), (17, 4), (17, 2), (7, 2), (7, 4), (8, 4), (8, 12),
        (6, 14), (6, 16), (11.2, 16), (11.2, 22), (12.8, 22), (12.8, 16),
        (18, 16), (18, 14),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(18, 18)
        context = self.get_style_context()
        context.add_class("sc-pin-icon")
        self.connect("draw", self._on_draw)

    def set_on(self, on: bool) -> None:
        context = self.get_style_context()
        if on:
            context.add_class("on")
        else:
            context.remove_class("on")

    def _on_draw(self, _widget, cr) -> bool:
        context = self.get_style_context()
        color = context.get_color(context.get_state())
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        scale = min(width, height) / 24.0
        cr.translate((width - 24 * scale) / 2, (height - 24 * scale) / 2)
        cr.scale(scale, scale)

        cr.move_to(*self.PATH[0])
        for point in self.PATH[1:]:
            cr.line_to(*point)
        cr.close_path()
        Gdk.cairo_set_source_rgba(cr, color)
        cr.fill()
        return False


class Popup:
    def __init__(self, app) -> None:
        self.app = app
        self.window: Gtk.Window | None = None
        self.entry: Gtk.SearchEntry | None = None
        self.list_box: Gtk.Box | None = None
        self.scroller: Gtk.ScrolledWindow | None = None
        self.hint: Gtk.Label | None = None
        self.rows: list[Gtk.EventBox] = []
        self.filtered: list[Clip] = []
        self.selected = 0
        self.query = ""
        self.visible = False
        self._shown_at = 0.0
        self._thumbs: dict[str, object] = {}
        self.pointer = Pointer()
        self._build()

    # ---------------------------------------------------------------- build

    def _build(self) -> None:
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.window.set_accept_focus(True)
        self.window.set_focus_on_map(True)
        self.window.set_default_size(self.app.config.popup_width, 120)
        self.window.get_style_context().add_class("sc-popup")
        self.window.connect("draw", self._on_draw)
        self.window.connect("key-press-event", self._on_key)
        self.window.connect("focus-out-event", self._on_focus_out)
        self.window.connect("delete-event", self._on_delete)

        try:
            screen = self.window.get_screen()
            visual = screen.get_rgba_visual()
            if visual is not None and screen.is_composited():
                self.window.set_visual(visual)
            self.window.set_app_paintable(True)
        except Exception:
            pass

        self._load_css()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.add(outer)

        self.title = Gtk.Label(label="Clipboard", xalign=0.0)
        self.title.get_style_context().add_class("sc-popup-title")
        outer.pack_start(self.title, False, False, 0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.get_style_context().add_class("sc-header")
        outer.pack_start(header, False, False, 0)

        self.entry = Gtk.SearchEntry()
        self.entry.get_style_context().add_class("sc-search")
        self.entry.set_hexpand(True)
        self.entry.connect("changed", self._on_search_changed)
        self.entry.connect("key-press-event", self._on_entry_key)
        self.entry.connect("activate", lambda *_: self._choose(self.selected))
        header.pack_start(self.entry, True, True, 0)

        self.settings_button = Gtk.Button()
        self.settings_button.get_style_context().add_class("sc-tool")
        self.settings_button.set_relief(Gtk.ReliefStyle.NONE)
        self.settings_button.set_can_focus(False)
        self.settings_button.set_tooltip_text("Settings")
        self.settings_button.add(
            Gtk.Image.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        )
        self.settings_button.connect("clicked", lambda _b: self._open_settings())
        header.pack_start(self.settings_button, False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_max_content_height(self.app.config.popup_max_height)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.get_style_context().add_class("sc-list")
        outer.pack_start(self.scroller, True, True, 0)

        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.list_box.set_spacing(0)
        self.scroller.add(self.list_box)

        self.hint = Gtk.Label(xalign=0.0)
        self.hint.set_line_wrap(True)
        self.hint.set_max_width_chars(52)
        self.hint.get_style_context().add_class("sc-hint")
        self.hint.set_no_show_all(True)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.get_style_context().add_class("sc-footer")
        footer.pack_start(self.hint, True, True, 0)
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

    # ------------------------------------------------------------- contents

    def refresh(self) -> None:
        if self.list_box is None:
            return
        for child in list(self.list_box.get_children()):
            self.list_box.remove(child)
        self.rows = []

        self.filtered = self.app.store.search(self.query, self.app.config.max_items)
        self.selected = min(self.selected, max(0, len(self.filtered) - 1))

        active = self.app.active_key
        if not self.filtered:
            empty = Gtk.Label(label="No clips yet" if not self.query else "No match")
            empty.get_style_context().add_class("sc-empty")
            self.list_box.pack_start(empty, False, False, 0)
            self._update_hint(0)
            self.list_box.show_all()
            return

        # Pinned clips come first; label the groups like the settings
        # sections so the two windows read the same way.
        pinned = [c for c in self.filtered if c.pinned]
        recent = [c for c in self.filtered if not c.pinned]
        index = 0
        for title, group in (("Pinned", pinned), ("Recent", recent)):
            if not group:
                continue
            self._add_section(title)
            for clip in group:
                row = self._make_row(clip, index, clip.key == active)
                self.rows.append(row)
                self.list_box.pack_start(row, False, False, 0)
                index += 1

        self._update_hint(len(self.filtered))
        self.list_box.show_all()
        self._select(self.selected)

    def _add_section(self, title: str) -> None:
        label = Gtk.Label(label=title, xalign=0.0)
        label.get_style_context().add_class("sc-section")
        self.list_box.pack_start(label, False, False, 0)

    def _make_row(self, clip: Clip, index: int, is_active: bool) -> Gtk.EventBox:
        row = Gtk.EventBox()
        ctx = row.get_style_context()
        ctx.add_class("sc-row")
        if is_active:
            ctx.add_class("sc-active")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class("sc-row-content")

        if clip.kind == IMAGE:
            box.get_style_context().add_class("sc-image")
            box.pack_start(self._make_thumb(clip), False, False, 0)

        preview = Gtk.Label(label=self._row_label(clip))
        preview.get_style_context().add_class("sc-preview")
        preview.set_xalign(0.0)
        preview.set_ellipsize(Pango.EllipsizeMode.END)
        preview.set_hexpand(True)
        preview.set_max_width_chars(10)
        box.pack_start(preview, True, True, 0)

        meta = Gtk.Label(label=_format_age(clip.created))
        meta.get_style_context().add_class("sc-meta")
        box.pack_start(meta, False, False, 0)

        pin = Gtk.Button()
        pin.get_style_context().add_class("sc-pin")
        pin.set_tooltip_text("Unpin" if clip.pinned else "Pin (Ctrl+P)")
        pin.set_relief(Gtk.ReliefStyle.NONE)
        pin.set_can_focus(False)
        icon = PinIcon()
        icon.set_on(clip.pinned)
        pin.add(icon)
        pin.connect("clicked", lambda _b, c=clip: self._toggle_pin(c))
        box.pack_start(pin, False, False, 0)

        row.add(box)
        # The row shows a short preview; the tooltip carries the whole clip.
        row.set_tooltip_text(_tooltip_for(clip))
        row.connect("button-press-event", lambda _w, e, i=index: self._on_row_click(i, e))
        row.connect("enter-notify-event", lambda _w, e, i=index: self._select(i))
        return row

    def _make_thumb(self, clip: Clip) -> Gtk.Widget:
        pixbuf = self._thumbs.get(clip.image)
        if pixbuf is None and clip.image:
            pixbuf = images.load_thumbnail(clip.image, THUMB_HEIGHT)
            if pixbuf is not None:
                self._thumbs[clip.image] = pixbuf
        if pixbuf is None:
            placeholder = Gtk.Label(label="\u25a1")
            placeholder.get_style_context().add_class("sc-thumb-missing")
            return placeholder
        thumb = Gtk.Image.new_from_pixbuf(pixbuf)
        thumb.get_style_context().add_class("sc-thumb")
        return thumb

    def _row_label(self, clip: Clip) -> str:
        if clip.kind == IMAGE:
            size = ""
            data_size = 0
            try:
                path = images.path_for(clip.image)
                if path.exists():
                    data_size = path.stat().st_size
            except OSError:
                pass
            if data_size:
                size = f" \u00b7 {_human_size(data_size)}"
            # A picture copied from the file manager keeps its file name,
            # which is far more recognisable than its pixel count.
            if clip.source:
                return f"{os.path.basename(clip.source)} \u00b7 {clip.width}\u00d7{clip.height}{size}"
            return f"Image {clip.width}\u00d7{clip.height}{size}"
        return _preview(clip.text)

    def _update_hint(self, count: int) -> None:
        if self.hint is None:
            return
        context = self.hint.get_style_context()
        context.remove_class("sc-warning")

        notice = getattr(self.app, "notice", "")
        if notice:
            detail = getattr(self.app, "notice_detail", "")
            self.hint.set_text(detail or notice)
            context.add_class("sc-warning")
            self.hint.show()
            return

        text = ""
        if count:
            text = "Enter paste \u00b7 Ctrl+P pin \u00b7 Ctrl+D delete \u00b7 Esc close"
        backend = self.app.paste_backend
        if self.app.config.paste and backend == "none" and self.app.config.show_paste_hint:
            if os.environ.get("WAYLAND_DISPLAY") and _on_gnome():
                extra = input_inject.extension_hint()
            else:
                cmd = input_inject.install_hint()
                extra = (
                    f"Install ydotool to paste automatically ({cmd})"
                    if cmd
                    else "Install ydotool to paste automatically"
                )
            text = extra if not text else f"{text}\n{extra}"
        if text:
            self.hint.set_text(text)
            self.hint.show()
        else:
            self.hint.hide()

    # -------------------------------------------------------------- control

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show()

    def _open_settings(self) -> None:
        self.hide()
        self.app.settings.show()

    def apply_config(self) -> None:
        """Re-apply size-related settings after the user edits them."""
        if self.scroller is not None:
            self.scroller.set_max_content_height(self.app.config.popup_max_height)
        if self.window is not None:
            self.window.set_size_request(self.app.config.popup_width, -1)
        self._size = None

    def show(self) -> None:
        self.app.sync_clipboard()
        self.query = ""
        if self.entry is not None:
            self.entry.set_text("")
        self.selected = 0
        self.refresh()
        assert self.window is not None
        self.window.show_all()
        if self.hint is not None and not self.hint.get_text():
            self.hint.hide()
        self.visible = True
        self._shown_at = time.time()
        GLib.idle_add(self._place)

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()
        self.visible = False
        # A warning is shown once: clearing it here means it disappears when
        # the popup closes, whether it was seen live or on the next open.
        self.app.notice = ""
        self.app.notice_detail = ""

    def _place(self) -> bool:
        assert self.window is not None
        self._apply_size()
        point = self.pointer.get()
        px = int(point[0]) if point else None
        py = int(point[1]) if point else None
        width, height = self._placement_size()

        display = Gdk.Display.get_default()
        monitor = None
        if display is not None and px is not None:
            monitor = display.get_monitor_at_point(px, py)
        if monitor is not None:
            area = monitor.get_workarea()
            x, y = compute_position(
                px, py, width, height,
                (area.x, area.y, area.width, area.height),
            )
        elif px is not None:
            x, y = px + POINTER_OFFSET, py + POINTER_OFFSET
        else:
            x = y = 100

        self.window.move(int(x), int(y))
        self.window.present()
        if self.entry is not None:
            self.entry.grab_focus()
        return False

    def _apply_size(self) -> None:
        """Pin the popup to the configured width and the content height.

        Called once the window is mapped (from ``_place``), when GTK has
        already worked out the real size; ``get_preferred_size`` before
        mapping reports a bogus height for the first open. Re-applied
        whenever the width/height settings change.
        """
        width = self.app.config.popup_width
        self.window.set_size_request(width, -1)
        _minimum, natural = self.window.get_preferred_size()
        height = max(natural.height, 120)
        self.window.set_size_request(width, height)
        self._size = (width, height)

    def _placement_size(self) -> tuple[int, int]:
        """The popup's real size, known even before it is mapped."""
        size = getattr(self, "_size", None)
        if size and size[0] > 1 and size[1] > 1:
            return size
        _current_w, current_h = self.window.get_size()
        width = self.app.config.popup_width
        height = current_h if current_h > 1 else 120
        return width, height

    # ------------------------------------------------------------- handlers

    def _on_draw(self, widget, cr) -> bool:
        """Paint the CSS background ourselves.

        ``set_app_paintable(True)`` (needed for the rounded, composited
        window) disables GTK's default background painting, so without this
        the panel would stay transparent and unreadable.
        """
        allocation = widget.get_allocation()
        context = widget.get_style_context()
        Gtk.render_background(context, cr, 0, 0, allocation.width, allocation.height)
        Gtk.render_frame(context, cr, 0, 0, allocation.width, allocation.height)
        return False

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.query = entry.get_text()
        self.selected = 0
        self.refresh()

    def _on_entry_key(self, _widget, event) -> bool:
        return self._handle_key(event)

    def _on_key(self, _widget, event) -> bool:
        return self._handle_key(event)

    def _handle_key(self, event) -> bool:
        key = event.keyval
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)

        if key == Gdk.KEY_Escape:
            self.hide()
            return True
        if key in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self._select(self.selected + 1)
            return True
        if key in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self._select(self.selected - 1)
            return True
        if key == Gdk.KEY_Page_Down:
            self._select(self.selected + 5)
            return True
        if key == Gdk.KEY_Page_Up:
            self._select(self.selected - 5)
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._choose(self.selected)
            return True
        if ctrl and key in (Gdk.KEY_p, Gdk.KEY_P):
            self._toggle_pin_selected()
            return True
        if ctrl and key in (Gdk.KEY_d, Gdk.KEY_D):
            self._delete_selected()
            return True
        return False

    def _on_row_click(self, index: int, event) -> bool:
        if event.button == 1:
            self._select(index)
            self._choose(index)
            return True
        return False

    def _on_focus_out(self, _widget, _event) -> bool:
        if self.visible and (time.time() - self._shown_at) > 0.25:
            self.hide()
        return False

    def _on_delete(self, _widget, _event) -> bool:
        self.hide()
        return True

    # ------------------------------------------------------------ selection

    def _select(self, index: int) -> None:
        if not self.rows:
            return
        index = max(0, min(index, len(self.rows) - 1))
        for i, row in enumerate(self.rows):
            ctx = row.get_style_context()
            if i == index:
                ctx.add_class("sc-selected")
            else:
                ctx.remove_class("sc-selected")
        self.selected = index
        self._scroll_into_view(index)

    def _scroll_into_view(self, index: int) -> None:
        if self.scroller is None or index >= len(self.rows):
            return
        row = self.rows[index]
        adj = self.scroller.get_vadjustment()
        alloc = row.get_allocation()
        top = alloc.y - adj.get_value()
        view = adj.get_page_size()
        if top < 0:
            adj.set_value(alloc.y)
        elif top + alloc.height > view:
            adj.set_value(alloc.y + alloc.height - view)

    # --------------------------------------------------------------- actions

    def _toggle_pin(self, clip: Clip) -> None:
        self.app.store.pin(clip)
        self.refresh()

    def _toggle_pin_selected(self) -> None:
        if self.filtered and self.selected < len(self.filtered):
            self._toggle_pin(self.filtered[self.selected])

    def _delete_selected(self) -> None:
        if self.filtered and self.selected < len(self.filtered):
            clip = self.filtered[self.selected]
            self._thumbs.pop(clip.image, None)
            self.app.store.remove(clip)
            self.selected = max(0, self.selected - 1)
            self.refresh()

    def _choose(self, index: int) -> None:
        if not self.filtered or index >= len(self.filtered):
            return
        self.app.choose(self.filtered[index])
