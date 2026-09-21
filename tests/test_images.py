"""Image header probing must never decode the pixels."""

from __future__ import annotations

import io
import struct

from PIL import Image

from simpleclips import images


def png_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, "PNG")
    return buffer.getvalue()


def jpeg_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, "JPEG")
    return buffer.getvalue()


def gif_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("P", (width, height)).save(buffer, "GIF")
    return buffer.getvalue()


def bmp_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, "BMP")
    return buffer.getvalue()


def webp_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height)).save(buffer, "WEBP")
    return buffer.getvalue()


def test_probe_png():
    assert images.probe_size(png_bytes(300, 200)) == (300, 200)


def test_probe_jpeg():
    assert images.probe_size(jpeg_bytes(300, 200)) == (300, 200)


def test_probe_gif():
    assert images.probe_size(gif_bytes(120, 80)) == (120, 80)


def test_probe_bmp():
    assert images.probe_size(bmp_bytes(120, 80)) == (120, 80)


def test_probe_webp():
    assert images.probe_size(webp_bytes(120, 80)) == (120, 80)


def test_probe_unknown_returns_none():
    assert images.probe_size(b"not an image at all") is None


def test_probe_truncated_header_returns_none():
    assert images.probe_size(b"\x89PNG\r\n\x1a\n") is None


def test_dimensions_match_probe_for_known_format():
    data = png_bytes(64, 48)
    assert images.dimensions(data) == (64, 48)


def test_large_image_is_measured_without_decoding():
    # Build a PNG header claiming a huge size; the body is a valid but tiny
    # image, so a decoder would report the real (small) size. Probing the
    # header must report the claimed size and never touch pixel data.
    data = png_bytes(10, 10)
    forged = bytearray(data)
    struct.pack_into(">II", forged, 16, 20000, 20000)
    assert images.dimensions(bytes(forged)) == (20000, 20000)


# ----------------------------------------------- what goes on the clipboard


def test_jpeg_clip_is_offered_as_png():
    # Chromium asks the clipboard for image/png and nothing else, so sending
    # a JPEG reached the browser as an empty paste.
    data, mime = images.png_for_clipboard(jpeg_bytes(80, 60), "image/jpeg")
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_png_clip_is_passed_through_untouched():
    source = png_bytes(40, 30)
    data, mime = images.png_for_clipboard(source, "image/png")
    assert data is source
    assert mime == "image/png"


def test_missing_mime_still_yields_png():
    data, mime = images.png_for_clipboard(png_bytes(20, 20), "")
    assert mime == "image/png"


def test_undecodable_data_falls_back_to_the_original():
    junk = b"not an image"
    data, mime = images.png_for_clipboard(junk, "image/jpeg")
    assert data is junk
    assert mime == "image/jpeg"
