"""End-to-end processing pipeline for one image file."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .compose import ShadowSpec, compose, export, make_background, to_rgba
from .engine import RES_PRESETS, MattingEngine
from .refine import decontaminate, feather, fill_holes, guided_refine, refine_closed_form

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class ProcessOptions:
    # inference
    model: str = "birefnet"
    res_preset: str = "balanced"           # fast | balanced | max
    refine: str = "guided"                 # none | guided | matting
    fill_holes: bool = True                # restore micro-holes inside the subject
    feather_px: float = 0.0
    defringe: bool = False
    max_pixels: int = 30_000_000           # local cap (their web cap: 25 MP)
    # composition
    bg_mode: str = "transparent"           # transparent | color | blur | image
    bg_color: str = "#ffffff"
    bg_image: str | None = None
    blur_radius: float = 24.0
    shadow: ShadowSpec = field(default_factory=ShadowSpec)
    # output
    out_format: str = "png"                # png | webp | jpg
    suffix: str = "-nobg"
    quality: int = 95


@dataclass
class ProcessResult:
    src: Path
    out: Path
    ms: int
    width: int
    height: int
    coverage: float          # fraction of pixels with alpha > 0.5
    res_used: int
    engine_desc: str
    image: Image.Image       # composed result (RGBA unless opaque background)


def load_rgb(path: Path, max_pixels: int) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)          # honour EXIF orientation
    img = img.convert("RGB")
    if max_pixels and img.width * img.height > max_pixels:
        scale = (float(max_pixels) / (img.width * img.height)) ** 0.5
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    return img


def process_file(
    path: str | Path,
    opts: ProcessOptions,
    engine: MattingEngine,
    out_dir: str | Path | None = None,
) -> ProcessResult:
    path = Path(path)
    t0 = time.perf_counter()

    img = load_rgb(path, opts.max_pixels)
    res = RES_PRESETS.get(opts.res_preset, 1024)

    alpha = engine.infer_matte(img, res=res)

    gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    if opts.refine == "matting":
        refined = refine_closed_form(np.asarray(img), alpha)
        alpha = refined if refined is not None else guided_refine(alpha, gray)
    elif opts.refine == "guided":
        alpha = guided_refine(alpha, gray)

    if opts.fill_holes:
        alpha = fill_holes(alpha)

    if opts.feather_px:
        alpha = feather(alpha, opts.feather_px)

    rgb = np.asarray(img)
    if opts.defringe:
        rgb = decontaminate(rgb, alpha)

    fg = to_rgba(rgb, alpha)
    background = make_background(
        img.size,
        opts.bg_mode,
        color=opts.bg_color,
        original=img,
        custom=Image.open(opts.bg_image) if (opts.bg_mode == "image" and opts.bg_image) else None,
        blur_radius=opts.blur_radius,
    )
    shadow = None
    if opts.shadow.enabled:
        from .compose import shadow_layer

        shadow = shadow_layer(alpha, opts.shadow)
    result = compose(fg, background, shadow)

    fmt = opts.out_format
    if fmt in ("jpg", "jpeg") and background is None:
        fmt_used, ext = "jpg", ".jpg"       # keep legacy publish path working
    else:
        fmt_used, ext = fmt, {"jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "png": ".png"}[fmt]

    target_dir = Path(out_dir) if out_dir else path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{path.stem}{opts.suffix}{ext}"
    export(str(out_path), result, fmt_used, quality=opts.quality)

    ms = int((time.perf_counter() - t0) * 1000)
    return ProcessResult(
        src=path,
        out=out_path,
        ms=ms,
        width=img.width,
        height=img.height,
        coverage=float((alpha > 0.5).mean()),
        res_used=res,
        engine_desc=engine.description(),
        image=result,
    )
