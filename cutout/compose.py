"""Composition stage: matte + RGB -> final image.

Parallels the remove.bg editor capabilities recovered during recon:
transparent export, solid colour background, blurred original background,
custom background image, and a synthetic drop shadow (their server-side
``shadow`` layer is AI-assisted; ours is a classical compositor).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


def to_rgba(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
    """Combine an RGB array and a float matte into an RGBA image.

    Same math as the observed client compositor: matte -> alpha channel.
    """
    a = np.clip(alpha, 0.0, 1.0)
    rgba = np.dstack([rgb.astype(np.uint8), (a * 255.0 + 0.5).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise ValueError(f"invalid colour: {value!r}")
    return tuple(int(v[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def make_background(
    size: tuple[int, int],
    mode: str,
    color: str = "#ffffff",
    original: Image.Image | None = None,
    custom: Image.Image | None = None,
    blur_radius: float = 24.0,
) -> Image.Image | None:
    """Build the background layer for ``mode`` (``transparent`` -> None)."""
    w, h = size
    if mode == "transparent":
        return None
    if mode == "color":
        return Image.new("RGB", (w, h), hex_to_rgb(color))
    if mode == "blur":
        src = (original or Image.new("RGB", (w, h), (0, 0, 0))).convert("RGB")
        if src.size != (w, h):
            src = src.resize((w, h), Image.LANCZOS)
        return src.filter(ImageFilter.GaussianBlur(max(0.0, blur_radius)))
    if mode == "image":
        if custom is None:
            raise ValueError("background image mode requires a custom image")
        src = custom.convert("RGB")
        # cover-fit (like CSS background-size: cover)
        scale = max(w / src.width, h / src.height)
        new_size = (max(1, int(src.width * scale + 0.5)), max(1, int(src.height * scale + 0.5)))
        src = src.resize(new_size, Image.LANCZOS)
        left = (src.width - w) // 2
        top = (src.height - h) // 2
        return src.crop((left, top, left + w, top + h))
    raise ValueError(f"unknown background mode {mode!r}")


@dataclass
class ShadowSpec:
    enabled: bool = False
    color: str = "#000000"
    opacity: float = 0.35
    blur: float = 24.0
    offset_x: float = 0.0
    offset_y: float = 18.0


def shadow_layer(alpha: np.ndarray, spec: ShadowSpec) -> Image.Image:
    """Soft drop shadow derived from the matte shape."""
    a = Image.fromarray((np.clip(alpha, 0, 1) * 255).astype(np.uint8), "L")
    if spec.blur > 0:
        a = a.filter(ImageFilter.GaussianBlur(spec.blur))
    shadow = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    r, g, b = hex_to_rgb(spec.color)
    shadow[..., 0], shadow[..., 1], shadow[..., 2] = r, g, b
    shadow[..., 3] = (np.asarray(a, dtype=np.float32) * float(np.clip(spec.opacity, 0, 1))).astype(np.uint8)
    img = Image.fromarray(shadow, "RGBA")
    if spec.offset_x or spec.offset_y:
        img = img.transform(
            img.size,
            Image.AFFINE,
            (1, 0, -spec.offset_x, 0, 1, -spec.offset_y),
            resample=Image.BICUBIC,
        )
    return img


def compose(
    fg: Image.Image,
    background: Image.Image | None = None,
    shadow: Image.Image | None = None,
) -> Image.Image:
    """Alpha-composite shadow (under) and foreground (over) onto background.

    With ``background=None`` the result stays RGBA (transparent export).
    """
    base: Image.Image
    if background is None:
        base = Image.new("RGBA", fg.size, (0, 0, 0, 0))
    else:
        base = background.convert("RGBA")
    if shadow is not None:
        base = Image.alpha_composite(base, shadow)
    return Image.alpha_composite(base, fg)


def export(path: str, image: Image.Image, fmt: str, quality: int = 95) -> None:
    """Save ``image`` as png / webp (lossless) or jpg (flatten to white)."""
    fmt = fmt.lower()
    if fmt == "png":
        image.convert("RGBA").save(path, "PNG", optimize=True)
    elif fmt == "webp":
        image.convert("RGBA").save(path, "WEBP", lossless=True, quality=100)
    elif fmt in ("jpg", "jpeg"):
        img = image
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    else:
        raise ValueError(f"unsupported format {fmt!r}")
