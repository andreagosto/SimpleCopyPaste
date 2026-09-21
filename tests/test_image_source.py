"""Image clips remember, and expose, the file they came from."""

from __future__ import annotations

from simplecopypaste.popup import _tooltip_for
from simplecopypaste.store import IMAGE, Store

from test_store import make_png


def test_source_is_stored_and_reloaded():
    store = Store()
    store.add_image(make_png(), "image/png", 100, source="/home/u/Pictures/cat.png")
    clip = store.clips[0]
    assert clip.source == "/home/u/Pictures/cat.png"
    assert Store().clips[0].source == "/home/u/Pictures/cat.png"


def test_source_fills_in_when_the_same_image_is_copied_again():
    store = Store()
    store.add_image(make_png(), "image/png", 100)          # pasted image, no name
    store.add_image(make_png(), "image/png", 100, source="/tmp/pic.png")
    assert len(store.clips) == 1
    assert store.clips[0].source == "/tmp/pic.png"


def test_source_is_searchable():
    store = Store()
    store.add_image(make_png(), "image/png", 100, source="/home/u/Pictures/sunset.png")
    assert [c.kind for c in store.search("sunset")] == [IMAGE]


def test_tooltip_shows_the_file_name():
    store = Store()
    store.add_image(make_png(64, 48), "image/png", 100, source="/tmp/photo.png")
    tooltip = _tooltip_for(store.clips[0])
    assert "photo.png" in tooltip
    assert "64" in tooltip and "48" in tooltip
    assert "image/png" in tooltip
