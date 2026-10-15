"""Alpha-matte refinements.

These stages correspond to behaviours observable in the remove.bg client:
their result zip ships a dedicated ``semi_transparency`` layer (hair, glass,
motion blur) and the editor exposes edge-level tooling.  Locally we recover
those qualities with classical matting/refinement algorithms instead of a
second network:

  * ``guided_refine``   - fast full-resolution edge-aware matte refinement
  * ``refine_closed_form`` - pymatting closed-form alpha matting (best edges,
    slower; guarded by a pixel budget)
  * ``decontaminate``   - removes background colour bleeding ("color fringe")
    at partially transparent pixels
"""
from __future__ import annotations

import logging

import numpy as np
from scipy.ndimage import gaussian_filter

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- helpers
def _box_filter(arr: np.ndarray, radius: int) -> np.ndarray:
    """Fast box filter via integral image (matches guided-filter definition)."""
    r = max(0, int(radius))
    if r == 0:
        return arr.copy()
    h, w = arr.shape
    pad = np.pad(arr, ((1, 0), (1, 0)), mode="reflect")
    integral = pad.cumsum(0).cumsum(1)
    ys, xs = np.mgrid[0:h, 0:w]
    y0 = np.clip(ys - r, 0, h)
    y1 = np.clip(ys + r + 1, 0, h)
    x0 = np.clip(xs - r, 0, w)
    x1 = np.clip(xs + r + 1, 0, w)
    total = (
        integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
    )
    count = (y1 - y0) * (x1 - x0)
    return total / np.maximum(count, 1).astype(arr.dtype)


def guided_refine(
    alpha: np.ndarray,
    guide_gray: np.ndarray,
    radius: int = 8,
    eps: float = 1e-3,
) -> np.ndarray:
    """Edge-aware refinement of the matte using the image as guide.

    A classic guided filter: wherever the image has an edge, the matte follows
    it instead of staying blurry — sharpens hair rims without hard aliasing.
    """
    a = alpha.astype(np.float32)
    g = guide_gray.astype(np.float32)
    mean_g = _box_filter(g, radius)
    mean_a = _box_filter(a, radius)
    corr_gg = _box_filter(g * g, radius)
    corr_ga = _box_filter(g * a, radius)
    var_g = corr_gg - mean_g * mean_g
    cov_ga = corr_ga - mean_g * mean_a
    A = cov_ga / (var_g + eps)
    B = mean_a - A * mean_g
    out = _box_filter(A, radius) * g + _box_filter(B, radius)
    return np.clip(out, 0.0, 1.0)


def _to_trimap(alpha: np.ndarray, lo: float = 0.03, hi: float = 0.97) -> np.ndarray:
    trimap = np.full(alpha.shape, 0.5, dtype=np.float32)
    trimap[alpha <= lo] = 0.0
    trimap[alpha >= hi] = 1.0
    return trimap


def refine_closed_form(
    rgb: np.ndarray,
    alpha: np.ndarray,
    max_pixels: int = 4_000_000,
    lo: float = 0.03,
    hi: float = 0.97,
) -> np.ndarray | None:
    """Closed-form alpha matting (Levin et al.) via pymatting.

    Returns ``None`` when the image exceeds ``max_pixels`` (the linear solve
    would be unpleasantly slow) so callers can fall back to ``guided_refine``.
    """
    if alpha.size > max_pixels:
        log.info("closed-form matting skipped (%d px > budget %d)", alpha.size, max_pixels)
        return None
    try:
        from pymatting import estimate_alpha_cf
    except Exception as exc:  # pragma: no cover
        log.warning("pymatting unavailable: %s", exc)
        return None

    image = rgb.astype(np.float64) / 255.0
    trimap = _to_trimap(alpha, lo, hi)
    if not np.any(trimap == 0.5):
        # nothing uncertain: matte is already binary
        return alpha
    out = estimate_alpha_cf(image, trimap)
    return np.clip(out.astype(np.float32), 0.0, 1.0)


def fill_holes(
    alpha: np.ndarray,
    threshold: float = 0.5,
    max_hole_frac: float = 0.001,
) -> np.ndarray:
    """Fill small background islands enclosed by the subject.

    Bright specular highlights are sometimes classified as background,
    leaving micro-holes inside the cutout (visible as speckles on chroma
    backgrounds).  Regions of ``alpha <= threshold`` that do not touch the
    image border get restored to foreground when they are small — bounded
    both relatively (``max_hole_frac`` of the image) and absolutely
    (``MIN_HOLE_PX``..``MAX_HOLE_PX``), so that legitimate enclosed gaps
    (e.g. the hole of a product handle) are never filled.
    """
    from scipy.ndimage import label

    MIN_HOLE_PX = 64
    MAX_HOLE_PX = 4096

    fg = alpha > threshold
    bg = ~fg
    if fg.sum() == 0 or bg.sum() == 0:
        return alpha
    lab, n = label(bg)
    if n == 0:
        return alpha
    border_ids = np.unique(
        np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    )
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    max_px = max(MIN_HOLE_PX, min(int(alpha.size * max_hole_frac), MAX_HOLE_PX))
    keep = np.zeros(n + 1, dtype=bool)
    keep[1:] = sizes[1:] <= max_px
    keep[border_ids] = False
    holes = keep[lab]
    if not holes.any():
        return alpha
    out = alpha.copy()
    out[holes] = 1.0
    return out


def feather(alpha: np.ndarray, px: float) -> np.ndarray:
    """Soften the matte edge by a gaussian blur of ``px`` pixels (0 = off)."""
    if px and px > 0:
        return np.clip(gaussian_filter(alpha.astype(np.float32), sigma=float(px)), 0.0, 1.0)
    return alpha


def decontaminate(rgb: np.ndarray, alpha: np.ndarray, sigma: float = 4.0) -> np.ndarray:
    """Remove background colour bleeding from edge pixels.

    Estimates the background colour field by diffusion from fully transparent
    pixels, then solves ``I = a*F + (1-a)*B`` for the foreground colour F at
    partially transparent pixels.
    """
    a = alpha.astype(np.float32)
    img = rgb.astype(np.float32) / 255.0
    weight_bg = (a < 0.05).astype(np.float32)
    if weight_bg.sum() < 16:
        return rgb
    num = np.stack([gaussian_filter(img[..., c] * weight_bg, sigma) for c in range(3)], axis=-1)
    den = gaussian_filter(weight_bg, sigma)[..., None]
    bg = num / np.maximum(den, 1e-6)
    a3 = a[..., None]
    fringe = ((a > 0.02) & (a < 0.98)).astype(np.float32)[..., None]
    fg = (img - (1.0 - a3) * bg) / np.maximum(a3, 1e-2)
    out = np.where(fringe > 0, fg, img)
    return (np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)
