"""Tests for the composition helpers (no model, no GPU required)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from cutout.compose import (
    ShadowSpec,
    compose,
    export,
    hex_to_rgb,
    make_background,
    shadow_layer,
    to_rgba,
)


def test_hex_to_rgb_variants():
    assert hex_to_rgb("#ff0000") == (255, 0, 0)
    assert hex_to_rgb("00ff00") == (0, 255, 0)
    assert hex_to_rgb("#0af") == (0, 170, 255)
    with pytest.raises(ValueError):
        hex_to_rgb("#12345")


def test_to_rgba_maps_matte_to_alpha():
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    alpha = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    img = to_rgba(rgb, alpha)
    assert img.mode == "RGBA"
    channel = np.asarray(img)[..., 3]
    assert channel[0, 0] == 0
    assert abs(int(channel[0, 1]) - 128) <= 1
    assert channel[1, 0] == 255
    assert abs(int(channel[1, 1]) - 64) <= 1


def test_make_background_modes():
    assert make_background((8, 8), "transparent") is None

    solid = make_background((8, 6), "color", color="#102030")
    assert solid.size == (8, 6) and solid.getpixel((0, 0)) == (16, 32, 48)

    original = Image.new("RGB", (16, 16), (200, 10, 10))
    blurred = make_background((8, 8), "blur", original=original, blur_radius=4)
    assert blurred.size == (8, 8)

    custom = Image.new("RGB", (40, 10), (0, 200, 0))
    cover = make_background((16, 16), "image", custom=custom)
    # cover-fit: portrait output from landscape source, both dims fully covered
    assert cover.size == (16, 16)
    with pytest.raises(ValueError):
        make_background((8, 8), "image")


def test_shadow_layer_alpha_and_offset():
    alpha = np.zeros((32, 32), dtype=np.float32)
    alpha[12:20, 12:20] = 1.0
    spec = ShadowSpec(enabled=True, color="#000000", opacity=0.5, blur=3, offset_y=4)
    layer = shadow_layer(alpha, spec)
    assert layer.mode == "RGBA" and layer.size == (32, 32)
    arr = np.asarray(layer)
    assert arr[..., 3].max() > 0
    # with a downward offset the shadow energy sits below the shape centre
    top = arr[:16, :, 3].sum()
    bottom = arr[16:, :, 3].sum()
    assert bottom > top


def test_compose_transparent_and_over_background():
    fg = Image.new("RGBA", (8, 8), (255, 0, 0, 128))
    transparent = compose(fg)
    assert transparent.mode == "RGBA"
    base = Image.new("RGB", (8, 8), (0, 0, 255))
    over = compose(fg, background=base)
    px = over.getpixel((4, 4))
    assert over.mode == "RGBA"
    assert px[2] > 100 and px[0] > 100  # blended red over blue


def test_export_formats(tmp_path):
    rgba = Image.new("RGBA", (8, 8), (10, 200, 30, 120))
    png = tmp_path / "out.png"
    export(str(png), rgba, "png")
    assert Image.open(png).mode == "RGBA"

    webp = tmp_path / "out.webp"
    export(str(webp), rgba, "webp")
    assert Image.open(webp).format == "WEBP"

    jpg = tmp_path / "out.jpg"
    export(str(jpg), rgba, "jpg")
    img = Image.open(jpg)
    assert img.mode == "RGB"
    with pytest.raises(ValueError):
        export(str(tmp_path / "x.gif"), rgba, "gif")
