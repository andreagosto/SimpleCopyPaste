"""Copied image files are resolved to the picture, not to their path."""

from __future__ import annotations

import io

from PIL import Image

from simpleclips.clipboard import (
    IMAGE_MIMES,
    parse_uri_list,
    _file_uri_to_path,
)
from simpleclips import clipboard as clipboard_mod


def test_parse_uri_list_plain():
    raw = "file:///home/user/a.png\nfile:///home/user/b.jpg\n"
    assert parse_uri_list(raw) == [
        "file:///home/user/a.png",
        "file:///home/user/b.jpg",
    ]


def test_parse_uri_list_gnome_copied_files():
    raw = "copy\nfile:///home/user/a.png"
    assert parse_uri_list(raw) == ["file:///home/user/a.png"]


def test_parse_uri_list_skips_comments_and_blanks():
    raw = "# comment\n\nfile:///tmp/x.png\n"
    assert parse_uri_list(raw) == ["file:///tmp/x.png"]


def test_file_uri_to_path_decodes_escapes():
    assert _file_uri_to_path("file:///tmp/my%20image.png") == "/tmp/my image.png"


def test_file_uri_to_path_rejects_remote_and_other_schemes():
    assert _file_uri_to_path("https://example.com/a.png") is None
    assert _file_uri_to_path("file://elsewhere/a.png") is None


# --------------------------------------------------------------- resolution


class FakeClipboard(clipboard_mod.Clipboard):
    """Clipboard whose reads come from a dict instead of the real system."""

    def __init__(self, types, bodies):
        self._backend = "wayland"
        self.resolve_image_files = True
        self._types = list(types)
        self._bodies = bodies

    def list_types(self):
        return list(self._types)

    def get_bytes(self, mime):
        return self._bodies.get(mime, b"")

    def get_text(self, mime="text/plain;charset=utf-8"):
        return self._bodies.get(mime, b"").decode("utf-8", "replace")


def png_file(tmp_path, name="shot.png"):
    path = tmp_path / name
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buffer, "PNG")
    path.write_bytes(buffer.getvalue())
    return path


def test_copied_image_file_yields_the_image(tmp_path):
    path = png_file(tmp_path)
    cb = FakeClipboard(
        ["text/uri-list", "text/plain;charset=utf-8"],
        {
            "text/uri-list": f"file://{path}\n".encode(),
            "text/plain;charset=utf-8": f"file://{path}".encode(),
        },
    )
    payload = cb.read()
    assert payload["kind"] == "image"
    assert payload["mime"] == "image/png"
    assert payload["data"].startswith(b"\x89PNG")
    assert payload["source"] == str(path)


def test_non_image_file_stays_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    cb = FakeClipboard(
        ["text/uri-list"],
        {"text/uri-list": f"file://{path}\n".encode()},
    )
    assert cb.read() is None  # no text/plain offered by this fake


def test_multiple_files_are_not_resolved(tmp_path):
    a = png_file(tmp_path, "a.png")
    b = png_file(tmp_path, "b.png")
    cb = FakeClipboard(
        ["text/uri-list", "text/plain"],
        {
            "text/uri-list": f"file://{a}\nfile://{b}\n".encode(),
            "text/plain": "anything".encode(),
        },
    )
    payload = cb.read()
    assert payload["kind"] == "text"


def test_missing_file_falls_back_to_text(tmp_path):
    missing = tmp_path / "gone.png"
    cb = FakeClipboard(
        ["text/uri-list", "text/plain"],
        {
            "text/uri-list": f"file://{missing}\n".encode(),
            "text/plain": f"file://{missing}".encode(),
        },
    )
    assert cb.read()["kind"] == "text"


def test_unsupported_image_format_falls_back_to_text(tmp_path):
    svg = tmp_path / "vector.svg"
    svg.write_text("<svg/>")
    cb = FakeClipboard(
        ["text/uri-list", "text/plain"],
        {
            "text/uri-list": f"file://{svg}\n".encode(),
            "text/plain": f"file://{svg}".encode(),
        },
    )
    assert cb.read()["kind"] == "text"


def test_resolution_can_be_disabled(tmp_path):
    path = png_file(tmp_path)
    cb = FakeClipboard(
        ["text/uri-list", "text/plain"],
        {
            "text/uri-list": f"file://{path}\n".encode(),
            "text/plain": f"file://{path}".encode(),
        },
    )
    cb.resolve_image_files = False
    assert cb.read()["kind"] == "text"


def test_supported_mime_list_matches_what_we_can_decode():
    assert "image/png" in IMAGE_MIMES
    assert "image/svg+xml" not in IMAGE_MIMES
