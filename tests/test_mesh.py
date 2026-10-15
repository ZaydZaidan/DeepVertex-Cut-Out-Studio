"""Tests for the 3D product-snapshot feature (no GL/torch required)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from cutout.mesh.camera import (
    PRESET_BUNDLES,
    VIEW_PRESETS,
    fit_radius,
    look_at,
    orthographic,
    perspective,
    view_direction,
)
from cutout.mesh.io import load_mesh, normalize
from cutout.mesh.shot import resolve_views


def _box_mesh(tmp_path: Path) -> Path:
    """STL cube side-stored like an uploaded product model."""
    mesh = trimesh.creation.box(extents=(40, 90, 30))
    path = tmp_path / "test-product.stl"
    mesh.export(str(path))
    return path


# ------------------------------------------------------------------ presets
def test_view_presets_cover_six_views_and_hero():
    for name in ("front", "back", "left", "right", "top", "bottom",
                 "hero-front-left", "hero-front-right"):
        assert name in VIEW_PRESETS
    assert PRESET_BUNDLES["standard"][:6] == ("front", "back", "left", "right", "top", "bottom")


def test_view_directions_unit_and_orthogonal_axis():
    assert np.allclose(np.linalg.norm(view_direction(0, 0)), 1.0)
    front = view_direction(0, 0)     # camera on +Z looking towards -Z
    right = view_direction(90, 0)    # camera on +X
    assert front[2] < -0.99 and abs(front[0]) < 0.01
    assert right[0] > 0.99 and abs(right[2]) < 0.01
    top = view_direction(0, 90)
    assert top[1] < -0.99  # camera above, looking down


def test_resolve_views_bundles_and_turntable():
    names, steps = resolve_views("standard")
    assert len(names) == 8 and steps == 0
    names, steps = resolve_views("turntable:8")
    assert steps == 8 and names == [f"spin-{i:02d}" for i in range(8)]
    names, _ = resolve_views("hero,front")
    assert names == list(PRESET_BUNDLES["hero"]) + ["front"]
    with pytest.raises(ValueError):
        resolve_views("nonsense")


# ------------------------------------------------------------------ matrices
def test_look_at_identity_target():
    pos = np.array([0.0, 0.0, 10.0])
    m = look_at(pos, np.zeros(3), np.array([0.0, 1.0, 0.0]))
    p = m @ np.array([*pos, 1.0])       # camera centre maps to origin

    assert np.allclose(p[:3], 0.0, atol=1e-9)


def test_perspective_and_orthographic_shapes():
    m = perspective(34.0, 1.0, 0.1, 100.0)
    assert m.shape == (4, 4)
    o = orthographic(50.0, 1.0, 0.1, 100.0)
    assert o.shape == (4, 4)
    # orthographic leaves x scaling independent of distance (no w term)
    assert o[3, 2] == 0.0


def test_fit_radius_fill():
    bounds = np.array([[0, 0, 0], [80, 90, 30]], dtype=float)
    r = fit_radius(bounds, fill=0.85)
    diag = np.linalg.norm(bounds[1] - bounds[0])
    assert r > 0 and abs(r - diag / (2 * 0.85)) < 1e-9


# ------------------------------------------------------------------ io
def test_load_stl_centres_mesh(tmp_path):
    mesh = load_mesh(_box_mesh(tmp_path))
    centre = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
    assert np.allclose(centre, 0.0, atol=1e-6)
    assert len(mesh.vertices) > 0


def test_normalize_puts_min_y_on_floor():
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    n = normalize(mesh)
    assert abs(n.bounds[0][1]) < 1e-9           # bottom rests on y = 0
    assert abs(n.bounds[1][1] - 20.0) < 1e-6    # full height above the floor


def test_fusion_native_rejected(tmp_path):
    p = tmp_path / "model.f3d"
    p.write_bytes(b"x")
    with pytest.raises(RuntimeError) as ei:
        load_mesh(p)
    assert "Fusion" in str(ei.value) and "Export" in str(ei.value)


def test_step_requires_optional_extra(tmp_path):
    p = tmp_path / "part.step"
    p.write_text("ISO-10303-21;")
    try:
        import cadquery  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("cadquery installed — availability branch unreachable")
    with pytest.raises(RuntimeError) as ei:
        load_mesh(p)
    msg = str(ei.value)
    assert "[step]" in msg or "STL" in msg
