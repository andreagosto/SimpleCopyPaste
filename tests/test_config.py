"""Config loading, saving and defaults."""

from __future__ import annotations

import json

from simpleclips import config
from simpleclips.config import Config

MB = 1024 * 1024


def test_defaults_include_persist_history():
    assert Config().persist_history is True


def test_default_image_limit_is_screenshot_sized():
    # 20 MP comfortably covers screenshots up to two 4K screens
    # (7680x2160 = 16.6 MP), while still rejecting camera photos.
    cfg = Config()
    assert cfg.max_image_pixels == 20_000_000
    assert cfg.max_image_pixels > 3840 * 2160          # single 4K
    assert cfg.max_image_pixels > 7680 * 2160          # two 4K, side by side
    assert cfg.max_image_bytes >= 64 * 1024 * 1024     # byte safety net


def test_save_and_reload_roundtrip():
    cfg = Config()
    cfg.max_items = 12
    cfg.popup_width = 480
    cfg.persist_history = False
    cfg.save()

    reloaded = Config.load()
    assert reloaded.max_items == 12
    assert reloaded.popup_width == 480
    assert reloaded.persist_history is False


def test_unknown_keys_are_ignored():
    path = config.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"max_items": 5, "nonsense": True}), encoding="utf-8")
    cfg = Config.load()
    assert cfg.max_items == 5


def test_corrupt_file_falls_back_to_defaults():
    path = config.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert Config.load().max_items == 20


def test_missing_file_falls_back_to_defaults():
    assert Config.load().max_items == 20
