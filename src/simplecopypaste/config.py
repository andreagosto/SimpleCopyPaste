"""XDG paths and persisted configuration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def _xdg(env: str, fallback: Path) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else fallback


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "simplecopypaste"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "simplecopypaste"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base)
    return Path("/tmp") / f"simplecopypaste-{os.getuid()}"


def config_file() -> Path:
    return config_dir() / "config.json"


def history_file() -> Path:
    return data_dir() / "history.json"


def images_dir() -> Path:
    return data_dir() / "images"


def socket_file() -> Path:
    return runtime_dir() / "simplecopypaste.sock"


def log_file() -> Path:
    return data_dir() / "simplecopypaste.log"


@dataclass
class Config:
    """User settings. Missing keys fall back to these defaults."""

    max_items: int = 20
    max_history: int = 100
    paste: bool = True
    paste_shortcut: str = "ctrl+v"
    popup_width: int = 560
    popup_max_height: int = 560
    show_paste_hint: bool = True
    autostart: bool = True
    images: bool = True
    image_files: bool = True
    max_image_pixels: int = 20_000_000
    max_image_bytes: int = 64 * 1024 * 1024
    persist_history: bool = True

    @classmethod
    def load(cls) -> "Config":
        path = config_file()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in raw.items() if k in known}
        try:
            return cls(**clean)
        except TypeError:
            return cls()

    def save(self) -> None:
        config_dir().mkdir(parents=True, exist_ok=True)
        _atomic_write(config_file(), json.dumps(asdict(self), indent=2))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
