"""Clipboard history persistence: recent items + pinned items.

Clips are either text or images. Text lives in the JSON history file;
images are stored as blobs under the data directory and referenced by
file name, so the history file stays small and readable.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, images

TEXT = "text"
IMAGE = "image"


@dataclass
class Clip:
    kind: str = TEXT
    text: str = ""
    image: str = ""
    mime: str = ""
    width: int = 0
    height: int = 0
    source: str = ""
    pinned: bool = False
    created: float = field(default_factory=time.time)
    count: int = 1

    @property
    def key(self) -> str:
        """Identity used for de-duplication."""
        return f"{self.kind}:{self.text}" if self.kind == TEXT else f"{self.kind}:{self.image}"

    @property
    def search_blob(self) -> str:
        if self.kind == TEXT:
            return self.text.lower()
        parts = f"image {self.width}x{self.height} {self.mime}"
        if self.source:
            parts += " " + Path(self.source).name
        return parts.lower()

    @classmethod
    def from_dict(cls, raw: dict) -> "Clip":
        kind = str(raw.get("kind", TEXT))
        return cls(
            kind=kind,
            text=str(raw.get("text", "")),
            image=str(raw.get("image", "")),
            mime=str(raw.get("mime", "")),
            width=int(raw.get("width", 0)),
            height=int(raw.get("height", 0)),
            source=str(raw.get("source", "")),
            pinned=bool(raw.get("pinned", False)),
            created=float(raw.get("created", time.time())),
            count=int(raw.get("count", 1)),
        )


class Store:
    """Ordered list of clips, most recent first.

    Invariants:
      - pinned clips are never evicted
      - identical clips are de-duplicated (moved to the front, counter bumped)
      - on disk as JSON, written atomically
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.history_file()
        self.clips: list[Clip] = []
        self.load()

    def load(self) -> None:
        self.clips = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        items = raw.get("clips", raw) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        for entry in items:
            if not isinstance(entry, dict):
                continue
            clip = Clip.from_dict(entry)
            if clip.kind == IMAGE and clip.image:
                self.clips.append(clip)
            elif clip.text:
                self.clips.append(clip)

    def save(self) -> None:
        config._atomic_write(
            self.path,
            json.dumps({"version": 1, "clips": [asdict(c) for c in self.clips]}, indent=2),
        )

    # ------------------------------------------------------------------ add

    def add_text(self, text: str, max_history: int = 100) -> Clip | None:
        if not text:
            return None
        return self._add(Clip(kind=TEXT, text=text), max_history)

    def add_image(
        self, data: bytes, mime: str, max_history: int = 100, source: str = ""
    ) -> Clip | None:
        saved = images.save(data, mime)
        if saved is None:
            return None
        name, width, height = saved
        clip = Clip(
            kind=IMAGE, image=name, mime=mime, width=width, height=height, source=source
        )
        return self._add(clip, max_history)

    def _add(self, clip: Clip, max_history: int) -> Clip:
        existing = self._find(clip.key)
        if existing is not None:
            existing.count += 1
            existing.created = time.time()
            if clip.source and not existing.source:
                existing.source = clip.source
            self.clips.remove(existing)
            self.clips.insert(0, existing)
            self._trim(max_history)
            self.save()
            return existing
        self.clips.insert(0, clip)
        self._trim(max_history)
        self.save()
        return clip

    # ------------------------------------------------------------- mutation

    def bump(self, clip: Clip) -> Clip:
        """Move an existing clip back to the front (used after re-copying)."""
        self._add(clip, 10 ** 9)
        return clip

    def pin(self, clip: Clip, pinned: bool | None = None) -> None:
        clip.pinned = (not clip.pinned) if pinned is None else pinned
        self.save()

    def remove(self, clip: Clip) -> None:
        if clip in self.clips:
            self.clips.remove(clip)
            self.save()
            self._collect()

    def get(self, key: str) -> Clip | None:
        return self._find(key)

    def clear_unpinned(self) -> None:
        self.clips = [c for c in self.clips if c.pinned]
        self.save()
        self._collect()

    # ----------------------------------------------------------------- read

    def ordered(self, max_items: int | None = None) -> list[Clip]:
        """Pinned first (still recency-ordered), then the rest."""
        pinned = [c for c in self.clips if c.pinned]
        rest = [c for c in self.clips if not c.pinned]
        result = pinned + rest
        if max_items is not None:
            result = result[:max_items]
        return result

    def search(self, query: str, max_items: int | None = None) -> list[Clip]:
        clips = self.ordered(max_items)
        needle = query.strip().lower()
        if not needle:
            return clips
        return [c for c in clips if needle in c.search_blob]

    # ---------------------------------------------------------------- intern

    def _find(self, key: str) -> Clip | None:
        for clip in self.clips:
            if clip.key == key:
                return clip
        return None

    def _trim(self, max_history: int) -> None:
        keep: list[Clip] = []
        unpinned = 0
        dropped: list[Clip] = []
        for clip in self.clips:
            if clip.pinned:
                keep.append(clip)
                continue
            unpinned += 1
            if unpinned <= max_history:
                keep.append(clip)
            else:
                dropped.append(clip)
        self.clips = keep
        for clip in dropped:
            self._delete_blob(clip)

    def _collect(self) -> None:
        """Drop image files that no stored clip references anymore."""
        referenced = {c.image for c in self.clips if c.kind == IMAGE and c.image}
        directory = config.images_dir()
        if not directory.exists():
            return
        for blob in directory.iterdir():
            if blob.is_file() and blob.name not in referenced:
                try:
                    blob.unlink()
                except OSError:
                    pass

    def _delete_blob(self, clip: Clip) -> None:
        if clip.kind == IMAGE and clip.image and self._find(clip.key) is None:
            images.delete(clip.image)
