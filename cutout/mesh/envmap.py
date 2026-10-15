"""Studio equirect environment map: procedural default + user override.

The default is a synthesised studio equirectangular (sky gradient, ceiling
softbox, horizon strip, dark floor) drawn as a bitmap — so reflections pick
up *shaped* light sources (a rectangle becomes a rectangle in the caustic),
which a purely analytic gradient could not give. A user-authored HDRI
(JPEG/PNG) can replace it via `--env-map PATH`.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def default_studio_equirect(res: tuple[int, int] = (2048, 1024)) -> np.ndarray:
    """Procedural studio environment: float32 RGB image in [0, 1].

    Layout (u: 0..1 across azimuth starting front, v: 0=top=zenith):
    * vertical sky gradient (bright top,
      ~0.55 mid, darker bottom),
    * soft bright floor not too dark (studio bounce),
    * a ceiling "softbox" — bright vertical rectangle between u .10-.38 (with
      soft gaussian edges) and v .16-.42,
    * a second rim/main slit strip behind at u .60-.72,
    * a horizon glow band around v .48-.55.
    """
    w, h = res
    u = np.linspace(0.0, 1.0, w, endpoint=False)[None, :, None]
    v = np.linspace(0.0, 1.0, h, endpoint=True)[:, None, None]

    # base vertical gradient (bright zenith, mid horizon, subdued floor)
    top = np.array([0.90, 0.91, 0.94])
    mid = np.array([0.62, 0.64, 0.68])
    bot = np.array([0.38, 0.39, 0.42])
    upper = top * (1 - v) + mid * v          # (h, w, 3)
    lower = mid * (1 - (v - 0.5) / 0.5) + bot * ((v - 0.5) / 0.5)
    env = np.where(v < 0.5, upper, lower)

    # soft floor bounce in the lower half (keeps the seated bottom readable)
    # (already covered by the mid→bot gradient — an extra sheen band:)
    env += 0.05 * np.exp(-((v - 0.62) / 0.10) ** 2)

    def soft_rect(u2: np.ndarray, v2: np.ndarray, cu, cv, wu, wv, strength):
        ellipse = ((u2 - cu) / wu) ** 2 + ((v2 - cv) / wv) ** 2
        gauss = np.exp(-ellipse * 4.2)
        edge = np.exp(-ellipse * 1.6) * 0.35
        return gauss * strength + edge * strength * 0.5

    # main ceiling softbox (upper front-left rectangle)
    env = np.clip(env + soft_rect(u, v, 0.24, 0.29, 0.135, 0.125, 3.6), 0.0, 1.0) * 1
    # secondary cool rim strip behind (adds edge shaping on silhouettes)
    env = np.clip(env + soft_rect(u, v, 0.66, 0.34, 0.055, 0.12, 1.7), 0.0, 1.0)
    # horizon glow band (bright line near eye level — gives streaks on verticals)
    env = np.clip(env + 0.55 * np.exp(-((v - 0.50) / 0.035) ** 2), 0.0, 1.0)
    return env.astype(np.float32)


def load_env(path: str | Path) -> np.ndarray:
    """Load a user-supplied equirect (JPEG/PNG) as float32 RGB in [0, 1]."""
    from PIL import Image

    img = Image.open(Path(path).expanduser()).convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    if arr.max(initial=1.0) > 1.05:  # some HDRIs are already normalized
        arr = arr / max(arr.max(), 1e-6)
    # gamma-linearise lightly (photographic inputs saved with sRGB curve)
    return np.clip(arr**1.9, 0.0, 1.0)


def env_texture_array(path: str | Path | None = None) -> np.ndarray:
    """Environment for the renderer: file when provided, else the default."""
    if path:
        return np.flipud(load_env(path))  # GL v=1 is row-last: flip so sky is v=1
    return np.flipud(default_studio_equirect())
