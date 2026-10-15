"""Tests for the alpha-refinement helpers (no model, no GPU required)."""
from __future__ import annotations

import numpy as np

from cutout.refine import _to_trimap, decontaminate, feather, fill_holes, guided_refine


def test_fill_holes_fills_enclosed_speck():
    alpha = np.ones((40, 40), dtype=np.float32)
    alpha[18:22, 18:22] = 0.0  # enclosed hole inside the subject
    fixed = fill_holes(alpha)
    assert fixed[18:22, 18:22].min() == 1.0


def test_fill_holes_keeps_border_connected_background():
    alpha = np.zeros((40, 40), dtype=np.float32)
    alpha[10:30, 10:30] = 1.0  # subject square; background touches the border
    fixed = fill_holes(alpha)
    assert fixed[0, 0] == 0.0 and fixed[39, 39] == 0.0
    assert fixed[20, 20] == 1.0


def test_fill_holes_respects_size_budget():
    alpha = np.ones((60, 60), dtype=np.float32)
    alpha[10:50, 10:50] = 0.0  # huge hole (larger than the default budget)
    fixed = fill_holes(alpha, max_hole_frac=0.001)
    assert fixed[20, 20] == 0.0


def test_feather_softens_edge():
    alpha = np.zeros((40, 40), dtype=np.float32)
    alpha[:, 20:] = 1.0
    soft = feather(alpha, 2.0)
    assert soft.shape == alpha.shape
    assert 0.0 < soft[20, 19] < 1.0  # edge pixel becomes fractional
    assert soft[20, 39] > 0.9


def test_guided_refine_shape_and_range():
    rng = np.random.default_rng(0)
    alpha = rng.random((30, 30)).astype(np.float32)
    guide = rng.random((30, 30)).astype(np.float32)
    out = guided_refine(alpha, guide, radius=4, eps=1e-3)
    assert out.shape == alpha.shape
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_decontaminate_reduces_green_spill():
    # red subject on a green background; edge pixels are green-contaminated
    rgb = np.zeros((24, 24, 3), dtype=np.uint8)
    rgb[..., 1] = 255  # green background everywhere
    rgb[4:20, 4:20] = (255, 0, 0)  # red subject
    alpha = np.zeros((24, 24), dtype=np.float32)
    alpha[4:20, 4:20] = 1.0
    # simulate spill: a semi-transparent edge pixel mixed with green
    alpha[4, 4] = 0.5
    rgb[4, 4] = (128, 128, 0)
    out = decontaminate(rgb, alpha)
    assert out.shape == rgb.shape and out.dtype == np.uint8
    assert int(out[4, 4, 1]) <= int(rgb[4, 4, 1])


def test_trimap_thresholds():
    alpha = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    trimap = _to_trimap(alpha)
    assert trimap[0, 0] == 0.0 and trimap[0, 1] == 0.5 and trimap[0, 2] == 1.0
