# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-10-15

### Added

- **3D Product Snapshot renderer** (`cutout.mesh`, CLI `cutout-mesh`,
  GUI *Process ▸ 3D Product Snapshot…*): renders web-shop-ready product
  images straight from **STEP / STL / OBJ / PLY / GLB** models. Six CAD
  views (orthographic), 3/4 *hero* angles, turntable spins, five background
  modes (transparent / pure-white / studio / dark / sunset / custom colour),
  two-lobe soft contact shadow, product-fill framing (85 % default), PNG /
  WebP / JPG output and a contact sheet. Headless GPU OpenGL (moderngl EGL,
  OSMesa/GLX fallback). Study: `docs/3D_SNAPSHOT_RECON.md`.
- Drag & drop of 3D files onto the picture window opens the snapshot dialog.
- Optional extra `[step]` (cadquery/OpenCASCADE) enables STEP import;
  Fusion `.f3d` files get an actionable export-guide error.

## [1.0.0] - 2026-10-15

### Added

- Initial public release.
- **Matting engine** (`cutout.engine`): Hugging Face backends for
  BiRefNet-general (MIT, default) and RMBG-2.0 (BRIA non-commercial, gated);
  lazy torch import; fp16-checkpoint dtype alignment (input dtype follows the
  loaded weights; model cast to fp32 on CPU) with automatic fp32 fallback.
- **Refinement** (`cutout.refine`): guided-filter alpha refinement,
  closed-form matting via pymatting (auto-skipped above ~4 MP), micro-hole
  filling, edge feathering, background-colour decontamination (defringe).
- **Composition** (`cutout.compose`): transparent / solid colour / blurred
  original / custom-image backgrounds, configurable drop shadow, PNG / WebP /
  JPG export.
- **Pipeline** (`cutout.pipeline`): EXIF-transpose normalization, pixel cap,
  single `process_file` entry used by both frontends.
- **CLI** (`cutout.cli`): batch processing of files and directories with
  model / quality / refine / feather / defringe / background / shadow /
  format / suffix options, `--cpu`, `--prefetch-model`, `--list-models`.
- **GUI** (`cutout.gui`): PySide6 desktop app with drag & drop, thumbnail
  queue, before/after checkerboard preview, background worker thread,
  keyboard shortcuts, tooltips, and an About dialog.
- **Packaging & CI**: `pyproject.toml` with `cutout-studio` and `cutout`
  console scripts; GitHub Actions workflow (ruff + pytest on Python 3.10/3.12,
  sdist/wheel build verification).
- **QA tooling** (`scripts/`): offscreen GUI smoke test, numeric quality
  check, widget-geometry UX audit; launcher (`run.sh`) that bundles the Qt
  xcb dependency (`libxcb-cursor.so.0`) without sudo.
