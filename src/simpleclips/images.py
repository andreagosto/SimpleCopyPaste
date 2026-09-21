"""Image clips: on-disk blobs, thumbnails and cleanup."""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import config
from .gtk_ui import GdkPixbuf  # ensures GTK/X11 backend is configured first

EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
}


def path_for(name: str) -> Path:
    return config.images_dir() / name


def save(data: bytes, mime: str) -> tuple[str, int, int] | None:
    """Persist raw image bytes. Returns (filename, width, height) or None."""
    pixbuf = _pixbuf_from_bytes(data)
    if pixbuf is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    name = digest + EXTENSIONS.get(mime, ".img")
    target = path_for(name)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
    return name, pixbuf.get_width(), pixbuf.get_height()


def decode(data: bytes):
    return _pixbuf_from_bytes(data)


def dimensions(data: bytes) -> tuple[int, int] | None:
    """Pixel size of the image.

    Reads the format header instead of decoding, so an enormous image is
    measured (and can be rejected) without ever allocating its pixels.
    Falls back to a real decode for formats without a known header, and
    only for reasonably small inputs.
    """
    size = probe_size(data)
    if size is not None:
        return size
    if len(data) > FALLBACK_DECODE_LIMIT:
        return None
    pixbuf = _pixbuf_from_bytes(data)
    if pixbuf is None:
        return None
    return pixbuf.get_width(), pixbuf.get_height()


# A decode fallback is only tried for inputs this small; anything larger
# with an unknown header is treated as unsupported rather than risk an
# unbounded allocation.
FALLBACK_DECODE_LIMIT = 8 * 1024 * 1024


def probe_size(data: bytes) -> tuple[int, int] | None:
    """Read width/height from a common image header without decoding."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            # IHDR is always the first chunk: width and height are big-endian.
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return (width, height) if width and height else None

        if data[:2] == b"\xff\xd8" and len(data) > 4:  # JPEG
            return _jpeg_size(data)

        if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            width = int.from_bytes(data[6:8], "little")
            height = int.from_bytes(data[8:10], "little")
            return (width, height) if width and height else None

        if data[:2] == b"BM" and len(data) >= 26:  # BMP
            width = int.from_bytes(data[18:22], "little", signed=True)
            height = int.from_bytes(data[22:26], "little", signed=True)
            return (abs(width), abs(height)) if width and height else None

        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            return _webp_size(data)
    except (IndexError, ValueError):
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Walk JPEG segments to the Start-Of-Frame, which holds the size."""
    index = 2
    length = len(data)
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xFF, 0x01) or 0xD0 <= marker <= 0xD9:
            index += 2
            continue
        segment = int.from_bytes(data[index + 2:index + 4], "big")
        if segment < 2:
            return None
        if marker in sof_markers:
            height = int.from_bytes(data[index + 5:index + 7], "big")
            width = int.from_bytes(data[index + 7:index + 9], "big")
            return (width, height) if width and height else None
        index += 2 + segment
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X":  # extended format, canvas size in the header
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 ":  # lossy: 14-byte frame header then dimensions
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        if width and height:
            return width, height
        return None
    if chunk == b"VP8L":  # lossless: 14-bit dimensions packed in 4 bytes
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None


def read(name: str) -> bytes | None:
    try:
        return path_for(name).read_bytes()
    except OSError:
        return None


def delete(name: str) -> None:
    try:
        path_for(name).unlink(missing_ok=True)
    except OSError:
        pass


def load_thumbnail(name: str, height: int = 44):
    """Return a scaled GdkPixbuf for the popup, or None if unreadable."""
    target = path_for(name)
    if not target.exists():
        return None
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(target), -1, height, True
        )
    except Exception:
        return None


def _pixbuf_from_bytes(data: bytes):
    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
    except Exception:
        return None
    return loader.get_pixbuf()
