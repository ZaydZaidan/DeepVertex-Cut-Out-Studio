"""Camera presets and small math helpers for product-snapshot rendering.

Coordinates: right-handed, +Y is up (product height), the *front* of the
product faces the viewer standing at +Z.  An "azimuth" rotates the camera
around the product (0 deg = front, 90 deg = right side, 180 = back);
"elevation" tilts it from the horizon (+90 = top view).

Naming convention follows the official CAD named views (Autodesk Fusion
drawing views: front / back / left / right / top / bottom) and the marketing
frames used by product pages (the 3/4 "hero" shots).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ViewPreset:
    name: str
    azimuth_deg: float   # 0 = front (+Z), +90 = right (+X), 180 = back
    elevation_deg: float  # 0 = horizon, +90 = top, -90 = bottom
    perspective: bool = True


#: classic six orthographic views CAD named views + marketing hero angles
VIEW_PRESETS: dict[str, ViewPreset] = {
    "front":      ViewPreset("front",   0.0,  0.0, perspective=False),
    "back":       ViewPreset("back", 180.0,  0.0, perspective=False),
    "left":       ViewPreset("left", -90.0,  0.0, perspective=False),
    "right":      ViewPreset("right", 90.0,  0.0, perspective=False),
    "top":        ViewPreset("top",    0.0, 90.0, perspective=False),
    "bottom":     ViewPreset("bottom", 0.0, -90.0, perspective=False),
    # e-commerce hero quarter views (front 3/4 and rear 3/4)
    "hero-front-left":  ViewPreset("hero-front-left",  -35.0, 22.0),
    "hero-front-right": ViewPreset("hero-front-right",  35.0, 22.0),
    "hero-back-left":   ViewPreset("hero-back-left",  -145.0, 22.0),
    "hero-back-right":  ViewPreset("hero-back-right",  145.0, 22.0),
}

#: preset bundles offered on the CLI / dialog
PRESET_BUNDLES: dict[str, tuple[str, ...]] = {
    "all":      ("front", "back", "left", "right", "top", "bottom",
                 "hero-front-left", "hero-front-right",
                 "hero-back-left", "hero-back-right"),
    "ortho":    ("front", "back", "left", "right", "top", "bottom"),
    "hero":     ("hero-front-left", "hero-front-right",
                 "hero-back-left", "hero-back-right"),
    "standard": ("front", "back", "left", "right", "top", "bottom",
                 "hero-front-left", "hero-front-right"),
}


def view_direction(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Unit direction from the camera *towards* the target (origin)."""
    az = np.radians(azimuth_deg)
    el = np.radians(elevation_deg)
    return np.array([
        np.sin(az) * np.cos(el),
        -np.sin(el),
        -np.cos(az) * np.cos(el),
    ], dtype=np.float64)


def camera_position(radius: float, azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Location of the camera on a sphere of *radius* around the target."""
    d = view_direction(azimuth_deg, elevation_deg)
    return -d * radius


def look_at(pos: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Standard right-handed look-at view matrix (column-vector convention)."""
    pos = np.asarray(pos, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    f = target - pos
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s_norm = np.linalg.norm(s)
    if s_norm < 1e-8:  # view direction parallel to up (top/bottom views)
        up = np.array([0.0, 0.0, 1.0]) if abs(f[1]) > 0.9 else np.array([0.0, 1.0, 0.0])
        s = np.cross(f, up)
        s_norm = np.linalg.norm(s)
    s /= s_norm
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, pos)
    m[1, 3] = -np.dot(u, pos)
    m[2, 3] = np.dot(f, pos)
    return m


def perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / np.tan(np.radians(fov_y_deg) / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def orthographic(
    half_height: float, aspect: float, near: float, far: float
) -> np.ndarray:
    m = np.eye(4)
    m[0, 0] = 1.0 / (half_height * aspect)
    m[1, 1] = 1.0 / half_height
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


def fit_radius(bounds: np.ndarray, fill: float = 0.85) -> np.ndarray:
    """Bounding-sphere radius of an axis-aligned *bounds* (2x3 min/max)."""
    size = bounds[1] - bounds[0]
    return 0.5 * float(np.linalg.norm(size)) / max(fill, 1e-6)
