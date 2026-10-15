"""Snapshot pipeline: mesh -> framed, lit, web-ready product images.

Usage:
    render_snapshots("bracket.stl", "/out", views="standard", bg="studio")

Output naming:  {stem}-{view}.png  +  {stem}-sheet.jpg (contact sheet).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .camera import (
    PRESET_BUNDLES,
    VIEW_PRESETS,
    camera_position,
    fit_radius,
    look_at,
    orthographic,
    perspective,
)
from .io import load_mesh  # noqa: F401 (re-export)
from .renderer import BACKGROUND_PRESETS

log = logging.getLogger(__name__)

FOV_Y_DEG = 34.0       # product-photography standard lens
DEFAULT_FILL = 0.85    # product fills >= 85% of the frame (e-commerce rule of thumb)


def resolve_views(spec: str) -> tuple[list[str], int]:
    """'standard' | 'all' | 'ortho' | 'hero' | 'front,back,...' | 'turntable:N'.

    Returns (view_names, spin_steps); *spin_steps* is 0 unless a turntable was
    requested, in which case view names are ``spin-ii`` (aq: steps-driven).
    """
    spec = (spec or "standard").strip().lower()
    known = set(VIEW_PRESETS) | set(PRESET_BUNDLES)
    if spec.startswith("turntable"):
        steps = 12
        if ":" in spec:
            steps = max(4, min(int(spec.split(":", 1)[1]), 72))
        return [f"spin-{i:02d}" for i in range(steps)], steps
    if spec in PRESET_BUNDLES:
        return list(PRESET_BUNDLES[spec]), 0
    names: list[str] = []
    for s in spec.split(","):
        s = s.strip()
        if not s:
            continue
        if s in PRESET_BUNDLES:      # allow bundles inside comma lists
            names.extend(PRESET_BUNDLES[s])
            continue
        if s.startswith("turntable"):
            sub, steps = resolve_views(s)
            names.extend(sub)
            continue
        if s not in known:
            raise ValueError(
                f"unknown view {s!r}; choose from {sorted(known)} or turntable:N"
            )
        names.append(s)
    return names, 0


def _spin_angles(name: str, steps: int) -> tuple[float, float]:
    """spin-ii -> (azimuth, elevation) for a *steps*-step turntable."""
    idx = int(name.split("-")[1])
    return idx * (360.0 / steps), 22.0


def _camera_for(mesh, name: str, fill: float, spin_steps: int = 0,
                perspective_hint: bool | None = None):
    """Camera for a view: (view_mat, cam_pos, kind, near, far).

    *kind* is 'ortho' (CAD six-view convention) or 'persp' (hero/turntable).
    The caller builds the projection: ortho needs ``half_height`` derived from
    the mesh extents; persp needs ``fov_y`` with *near*/*far*.
    """
    import numpy as np

    bounds = np.asarray(mesh.bounds)
    r_proj = fit_radius(bounds, fill=fill)
    if name.startswith("spin"):
        az, el = _spin_angles(name, spin_steps)
        fov = True if perspective_hint is None else perspective_hint
    elif name in VIEW_PRESETS:
        preset = VIEW_PRESETS[name]
        az, el = preset.azimuth_deg, preset.elevation_deg
        fov = preset.perspective if perspective_hint is None else perspective_hint
    else:
        raise ValueError(f"unknown view preset {name!r}")

    up = _up_for(az, el)
    pos = camera_position(r_proj * 2.5, az, el)
    view = look_at(pos, np.zeros(3), np.asarray(up, dtype=float))
    if fov:
        pos = camera_position(r_proj / np.tan(np.radians(FOV_Y_DEG) / 2), az, el)
        view = look_at(pos, np.zeros(3), np.asarray(up, dtype=float))
        return view, pos, "persp", r_proj * 0.2, r_proj * 20.0
    return view, pos, "ortho", r_proj * 0.1, r_proj * 6.0


def _up_for(azimuth_deg: float, elevation_deg: float):
    if abs(abs(elevation_deg) - 90.0) < 20.0:  # top/bottom: need a side up vector
        return (1.0, 0.0, 0.0)
    return (0.0, 1.0, 0.0)


def _shadow_mask(
    mesh, view_mat: np.ndarray, proj_mat: np.ndarray, size: int, light_dir: np.ndarray
):
    """Rasterise the mesh's soft contact shadow from above, in image space.

    Projects each vertex along the key-light direction onto the floor plane
    (y = mesh bottom) and paints the projected triangles. Returns (float32 HxW
    alpha mask 0..1) in *pixel order (rows from top)* — same rotation the GL
    framebuffer read uses.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    v = np.asarray(mesh.vertices)
    y0 = v[:, 1].min()
    d = np.asarray(light_dir, dtype=float)
    if abs(d[1]) < 1e-6:
        return np.zeros((size, size), dtype=np.float32)
    t = (y0 - v[:, 1]) / d[1]
    ground = v + np.outer(t, d)

    # project through the same camera
    corners = np.pad(ground, ((0, 0), (0, 1)), constant_values=1.0)
    clip = corners @ (proj_mat @ view_mat).T
    w = clip[:, 3]
    ok = np.abs(w) > 1e-9
    ndc = np.zeros_like(clip[:, :2])
    ndc[ok] = clip[ok, :2] / w[ok, None]
    px = (ndc[:, 0] * 0.5 + 0.5) * size
    py = (0.5 - ndc[:, 1] * 0.5) * size

    faces = np.asarray(mesh.faces)
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)
    pts = np.stack([px, py], axis=1)
    for f in faces:
        tri = [tuple(pts[i]) for i in f]
        draw.polygon(tri, fill=255)
    return np.asarray(img, dtype=np.float32) / 255.0


def _export(img: Image.Image, path: Path, fmt: str, flatten_color=(255, 255, 255)) -> None:
    if fmt == "png":
        img.save(path, "PNG")
    elif fmt == "webp":
        img.save(path, "WEBP", quality=95)
    elif fmt == "jpg":
        bg = Image.new("RGB", img.size, flatten_color)
        bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        bg.save(path, "JPEG", quality=92)
    else:
        raise ValueError(f"unsupported format {fmt!r}")


def _flatten_hex(hex_color: str):
    hx = hex_color.lstrip("#")
    return tuple(int(hx[i : i + 2], 16) for i in (0, 2, 4))


def _composite(rgb, alpha_prod, bg_tuple, shadow_mask):
    """Product RGBA (+ optional two-lobe soft floor shadow) -> uint8 HxWx4."""
    a_prod = np.clip(alpha_prod, 0.0, 1.0)[..., None].astype(np.float32)
    if shadow_mask is not None:
        wide = np.clip(shadow_mask.get("wide"), 0.0, 1.0)
        tight = np.clip(shadow_mask.get("tight"), 0.0, 1.0)
    else:
        wide = tight = np.zeros(np.shape(rgb)[:2], dtype=np.float32)

    if bg_tuple is not None:
        # GL pass already wrote the backdrop underneath the product: darken the
        # floor region: wide soft lobe + tight contact occlusion at the base.
        dark = 1.0 - np.clip(0.30 * wide + 0.45 * tight, 0.0, 0.55)
        rgbf = rgb.astype(np.float32) * dark[..., None]
        full = np.ones_like(rgbf[..., :1])
        return np.dstack([rgbf, full]).astype(np.uint8)

    # transparent: shadow carries alpha below the product silhouette
    a_shadow = np.clip(0.5 * wide + 0.55 * tight, 0.0, 0.8)[..., None]
    a_out = np.clip(a_prod + a_shadow * (1.0 - a_prod), 0.0, 1.0)
    rgbf = np.where(
        a_prod > 1e-3, rgb.astype(np.float32), np.zeros_like(rgb, dtype=np.float32)
    )
    return np.dstack([rgbf, a_out * 255.0]).astype(np.uint8)


def render_snapshots(
    model_path: str | Path,
    out_dir: str | Path,
    views_spec: str = "standard",
    bg: str = "studio",
    bg_color: str = "#ffffff",
    size: int = 1600,
    fmt: str = "png",
    shadow: str = "auto",
    fill: float = DEFAULT_FILL,
    sheet: bool = True,
    material: dict | None = None,
) -> list[Path]:
    """Render every requested view of *model_path* into *out_dir*.

    Background modes:
      transparent   alpha-0 canvas, no shadow (safe for stickers / composites)
      white         pure #FFFFFF — Amazon main-image rule (shadow off)
      studio        seamless studio gradient + soft contact shadow
      dark / sunset KeyShot-style gradient backdrops + contact shadow
      color         solid colour of your choice + contact shadow

    *shadow*: "auto" (on for studio/dark/sunset/color, off for transparent
    and white), "on", or "off".
    """
    from .renderer import GLRenderer

    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    size = max(256, min(int(size), 4096))
    if size % 2:
        size += 1

    views, spin_steps = resolve_views(views_spec)
    mesh = load_mesh(model_path)

    if bg == "transparent":
        bg_tuple, shadow_on = None, False
    elif bg == "white":
        bg_tuple, shadow_on = ((1.0, 1.0, 1.0, 1.0),) * 2, False
    elif bg in BACKGROUND_PRESETS:
        bg_tuple, shadow_on = BACKGROUND_PRESETS[bg], True
    elif bg == "color":
        rgb = tuple(c / 255.0 for c in _flatten_hex(bg_color))
        bg_tuple, shadow_on = ((rgb + (1.0,)),) * 2, True
    else:
        raise ValueError(f"unknown background {bg!r}")
    if shadow == "on":
        shadow_on = True
    elif shadow == "off":
        shadow_on = False

    flatten = (255, 255, 255) if bg != "color" else _flatten_hex(bg_color)
    outputs: list[Path] = []
    sheet_imgs: list[Image.Image] = []

    with GLRenderer(size=(size, size)) as renderer:
        for name in views:
            view, cam_pos, kind, near, far = _camera_for(
                mesh, name, fill=fill, spin_steps=spin_steps
            )
            if kind == "persp":
                proj = perspective(FOV_Y_DEG, aspect=1.0, near=near, far=far)
            else:
                proj = orthographic(
                    half_height=float(np.linalg.norm(mesh.extents)) * 0.5 / fill,
                    aspect=1.0, near=near, far=far,
                )
            rgb, alpha = renderer.render_mesh(mesh, view, proj, cam_pos, bg=bg_tuple)

            # product silhouette (needed to keep the shadow off the product
            # and for transparent mode alpha). In bg-transparent mode the GL
            # alpha *is* the silhouette; for opaque backdrops make an extra
            # silhouette pass.
            if bg_tuple is None:
                alpha_prod = alpha
            else:
                _, alpha_prod = renderer.render_mesh(
                    mesh, view, proj, cam_pos, bg=None
                )

            mask = None  # soft contact shadow (image space, on the floor only)
            if shadow_on:
                from .renderer import KEY_LIGHT

                raw = _shadow_mask(mesh, view, proj, size, KEY_LIGHT[0])
                soft = np.asarray(
                    Image.fromarray((raw * 255).astype(np.uint8)).filter(
                        ImageFilter.GaussianBlur(radius=max(8, size // 90))
                    ),
                    dtype=np.float32,
                ) / 255.0
                keep = np.clip(1.0 - alpha_prod, 0.0, 1.0)
                mask = np.clip(soft * keep, 0.0, 1.0)          # wide blurred lobe
                # tight contact occlusion: only the floor band *below* the
                # product's lowest silhouette row per column
                has_prod = alpha_prod > 0.3
                base_row = np.where(
                    has_prod.any(axis=0),
                    np.where(has_prod, np.arange(size)[:, None], 0).max(axis=0),
                    -1,
                )
                base = np.zeros((size, size), dtype=np.float32)
                cols = base_row >= 0
                if cols.any():
                    rows = np.arange(size)[:, None]
                    base[:, cols] = (
                        rows >= base_row[cols][None, :].astype(float) - float(max(8, size // 90))
                    ).astype(np.float32)
                contact = np.clip(raw * base * keep, 0.0, 1.0)
                contact = np.asarray(
                    Image.fromarray((contact * 255).astype(np.uint8)).filter(
                        ImageFilter.GaussianBlur(radius=max(10, size // 120))
                    ),
                    dtype=np.float32,
                ) / 255.0
                mask = dict(wide=mask, tight=contact)

            frame = Image.fromarray(
                _composite(rgb, alpha_prod, bg_tuple, mask), "RGBA"
            )
            fname = f"{mesh.name}-{name}.{fmt}"
            _export(frame, out_dir / fname, fmt, flatten_color=flatten)
            outputs.append(out_dir / fname)
            if sheet:
                sheet_imgs.append(frame.resize((360, 360), Image.LANCZOS))

    if sheet and len(sheet_imgs) > 1:
        cols = min(5, len(sheet_imgs))
        rows = (len(sheet_imgs) + cols - 1) // cols
        board = Image.new("RGB", (cols * 370 + 10, rows * 370 + 10), (24, 24, 28))
        for k, thumb in enumerate(sheet_imgs):
            r, c = divmod(k, cols)
            board.paste(
                thumb.convert("RGB"), (10 + c * 370 + (370 - thumb.width) // 2, 10 + r * 370)
            )
        name_sheet = out_dir / f"{mesh.name}-sheet.jpg"
        board.save(name_sheet, "JPEG", quality=88)
        outputs.append(name_sheet)
    log.info("rendered %d views -> %s", len(views), out_dir)
    return outputs
