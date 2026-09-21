"""Row tooltips expose the full clip, wrapped for long or unbroken text."""

from __future__ import annotations

from simpleclips.popup import TOOLTIP_CHARS, TOOLTIP_WIDTH, _tooltip_for, _wrap_for_tooltip
from simpleclips.store import IMAGE, TEXT, Clip


def test_text_tooltip_keeps_line_breaks():
    clip = Clip(kind=TEXT, text="line one\nline two")
    assert _tooltip_for(clip) == "line one\nline two"


def test_image_tooltip_reports_size_and_type():
    clip = Clip(kind=IMAGE, image="x.png", mime="image/png", width=480, height=300)
    tooltip = _tooltip_for(clip)
    assert "480" in tooltip and "300" in tooltip
    assert "image/png" in tooltip


def test_short_text_is_not_truncated():
    clip = Clip(kind=TEXT, text="hello")
    assert _tooltip_for(clip) == "hello"


def test_very_long_text_is_capped_with_a_note():
    clip = Clip(kind=TEXT, text="x" * (TOOLTIP_CHARS + 500))
    tooltip = _tooltip_for(clip)
    flat = tooltip.replace("\n", "")
    assert flat.startswith("x" * 100)
    assert "(preview truncated)" in tooltip
    assert len(flat) < TOOLTIP_CHARS + 100

def test_long_url_is_broken_into_lines():
    clip = Clip(kind=TEXT, text="https://example.com/" + "a" * 300)
    tooltip = _tooltip_for(clip)
    assert "\n" in tooltip
    assert max(len(line) for line in tooltip.split("\n")) <= TOOLTIP_WIDTH


def test_wrap_prefers_spaces():
    text = ("word " * 40).strip()
    wrapped = _wrap_for_tooltip(text, width=20)
    assert all(len(line) <= 20 for line in wrapped.split("\n"))
    # no word is cut in half when a space was available
    assert "wor\nd" not in wrapped


def test_wrap_keeps_blank_lines():
    assert _wrap_for_tooltip("a\n\nb") == "a\n\nb"
