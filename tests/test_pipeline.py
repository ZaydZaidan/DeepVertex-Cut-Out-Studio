"""End-to-end pipeline tests using a fake matting engine (no torch required)."""
from __future__ import annotations

import numpy as np
from PIL import Image

from cutout.pipeline import ProcessOptions, load_rgb, process_file


class FakeEngine:
    """Returns a centred square matte — exercises the full pipeline wiring."""

    def __init__(self) -> None:
        self.loaded = True

    def load(self) -> None:  # pragma: no cover - nothing to load
        pass

    def infer_matte(self, image: Image.Image, res: int = 1024, keep_aspect: bool = True) -> np.ndarray:
        w, h = image.size
        alpha = np.zeros((h, w), dtype=np.float32)
        alpha[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = 1.0
        return alpha

    def description(self) -> str:
        return "fake engine"


def make_image(path, size=(64, 64), color=(200, 30, 30)):
    Image.new("RGB", size, color).save(path)
    return path


def test_load_rgb_respects_pixel_cap(tmp_path):
    path = tmp_path / "big.jpg"
    make_image(path, size=(2000, 1000))
    img = load_rgb(path, max_pixels=250_000)
    assert img.width * img.height <= 250_000
    assert abs(img.width / img.height - 2.0) < 0.05  # aspect ratio preserved


def test_process_file_end_to_end_png(tmp_path):
    src = make_image(tmp_path / "photo.jpg")
    out_dir = tmp_path / "out"
    opts = ProcessOptions(refine="guided", out_format="png", suffix="-nobg")
    result = process_file(src, opts, FakeEngine(), out_dir=out_dir)

    assert result.out.exists() and result.out.name == "photo-nobg.png"
    assert result.width == 64 and result.height == 64
    assert 0.2 < result.coverage < 0.3  # centred quarter-square matte
    with Image.open(result.out) as img:
        assert img.mode == "RGBA"


def test_process_file_background_and_jpg(tmp_path):
    src = make_image(tmp_path / "card.png")
    opts = ProcessOptions(
        refine="none",
        bg_mode="color",
        bg_color="#101010",
        out_format="jpg",
        suffix="-flat",
    )
    result = process_file(src, opts, FakeEngine(), out_dir=tmp_path)
    with Image.open(result.out) as img:
        assert img.mode == "RGB"
        assert img.getpixel((1, 1)) == (16, 16, 16)  # background colour wins outside the matte


def test_process_file_fill_holes_and_feather(tmp_path):
    src = make_image(tmp_path / "x.png", size=(32, 32))
    opts = ProcessOptions(refine="none", fill_holes=True, feather_px=1.0, out_format="png")
    result = process_file(src, opts, FakeEngine(), out_dir=tmp_path)
    assert result.out.exists()
