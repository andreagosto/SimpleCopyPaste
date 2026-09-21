"""Store behaviour: de-duplication, pinning, trimming and image blobs."""

from __future__ import annotations

from simplecopypaste import config, images
from simplecopypaste.gtk_ui import GdkPixbuf
from simplecopypaste.store import IMAGE, TEXT, Store


def make_png(width: int = 64, height: int = 48, color: int = 0x2F6F4FFF) -> bytes:
    pixbuf = GdkPixbuf.Pixbuf.new(
        GdkPixbuf.Colorspace.RGB, True, 8, width, height
    )
    pixbuf.fill(color)
    _, data = pixbuf.save_to_bufferv("png", [], [])
    return data


def test_text_dedup_moves_to_front():
    store = Store()
    store.add_text("one")
    store.add_text("two")
    store.add_text("one")
    assert [c.text for c in store.clips] == ["one", "two"]
    assert store.clips[0].count == 2


def test_ignore_empty_text():
    store = Store()
    assert store.add_text("") is None
    assert store.add_text(None) is None
    assert store.clips == []


def test_pinned_clips_sort_first_and_survive_trim():
    store = Store()
    store.add_text("keep me")
    store.pin(store.clips[0])
    for i in range(20):
        store.add_text(f"filler {i}", max_history=3)
    texts = [c.text for c in store.clips]
    assert "keep me" in texts
    assert store.ordered()[0].text == "keep me"
    assert sum(1 for c in store.clips if not c.pinned) == 3


def test_image_dedup_keeps_single_blob():
    store = Store()
    data = make_png()
    first = store.add_image(data, "image/png")
    second = store.add_image(data, "image/png")
    assert first is second
    assert first.count == 2
    assert len(list(config.images_dir().iterdir())) == 1


def test_image_blob_removed_with_clip():
    store = Store()
    clip = store.add_image(make_png(), "image/png")
    assert images.path_for(clip.image).exists()
    store.remove(clip)
    assert not images.path_for(clip.image).exists()


def test_image_blob_removed_when_evicted_by_trim():
    store = Store()
    clip = store.add_image(make_png(), "image/png")
    store.add_text("newer", max_history=1)
    assert not images.path_for(clip.image).exists()
    assert all(c.kind == TEXT for c in store.clips)


def test_persistence_roundtrip():
    store = Store()
    store.add_text("hello")
    store.add_image(make_png(), "image/png")
    reloaded = Store()
    kinds = [c.kind for c in reloaded.clips]
    assert kinds == [IMAGE, TEXT]
    assert reloaded.clips[0].width == 64
    assert reloaded.clips[0].height == 48


def test_search_matches_text_and_image_metadata():
    store = Store()
    store.add_text("SELECT * FROM novels")
    store.add_image(make_png(320, 180), "image/png")
    assert [c.kind for c in store.search("select")] == [TEXT]
    assert [c.kind for c in store.search("image 320")] == [IMAGE]
    assert store.search("nope") == []


def test_clear_unpinned_keeps_pinned_and_collects_blobs():
    store = Store()
    pinned = store.add_image(make_png(), "image/png")
    store.pin(pinned)
    store.add_image(make_png(color=0xFF0000FF), "image/png")
    store.clear_unpinned()
    assert len(store.clips) == 1
    assert len(list(config.images_dir().iterdir())) == 1
