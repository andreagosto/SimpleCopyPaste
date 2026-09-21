"""Popup placement maths: flip around the cursor, clamp only as a fallback."""

from __future__ import annotations

from simpleclips.popup import compute_position

# A 2560x1440 monitor with a 56px panel, and a typical 560x475 popup.
AREA = (0, 0, 2560, 1384)
W, H = 560, 475


def test_opens_below_right_of_cursor_when_it_fits():
    assert compute_position(100, 100, W, H, AREA) == (114, 114)


def test_flips_up_and_left_near_bottom_right_corner():
    # 2106+14+560 exceeds 2560 and 1287+14+475 exceeds 1384, so instead of
    # being shoved into the corner the popup sits up-left of the cursor.
    assert compute_position(2106, 1287, W, H, AREA) == (2106 - W - 14, 1287 - H - 14)


def test_flips_only_horizontally_near_right_edge():
    assert compute_position(2500, 100, W, H, AREA) == (2500 - W - 14, 114)


def test_flips_only_vertically_near_bottom_edge():
    assert compute_position(100, 1300, W, H, AREA) == (114, 1300 - H - 14)


def test_clamps_top_left_when_pointer_at_origin():
    assert compute_position(0, 0, W, H, AREA) == (14, 14)


def test_clamps_when_popup_taller_than_workarea():
    tall = 2000
    x, y = compute_position(100, 1000, W, tall, AREA)
    assert x == 114
    assert y == 0  # flipped position was off-screen, so clamp wins


def test_respects_monitor_offset_on_second_screen():
    # Second monitor to the right (as in a dual-head layout).
    area = (2560, 0, 2560, 1384)
    x, y = compute_position(2700, 1300, W, H, area)
    assert x == 2700 + 14
    assert y == 1300 - H - 14


def test_never_leaves_the_workarea():
    area = (0, 0, 2560, 1384)
    for point in [(0, 0), (2559, 1383), (1280, 692), (0, 1383), (2559, 0)]:
        x, y = compute_position(point[0], point[1], W, H, area)
        assert area[0] <= x <= area[0] + area[2] - W
        assert area[1] <= y <= area[1] + area[3] - H
