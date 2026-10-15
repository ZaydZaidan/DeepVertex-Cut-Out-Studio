# Architecture

This document maps the modules, the data flow, and the device/dtype strategy.

## Module map

```
cutout/
├── __init__.py    # package version (no heavy imports)
├── engine.py      # MattingEngine: HF model backends → full-res float alpha matte
├── refine.py      # alpha clean-up: guided filter, closed-form matting, holes, feather, defringe
├── compose.py     # composition: backgrounds, drop shadow, export encoders
├── pipeline.py    # process_file(): the single per-file entry both frontends call
├── cli.py         # argparse CLI over process_file (files or directories)
└── gui.py         # PySide6 desktop app (queue, preview, background worker)
scripts/
├── gui_smoke.py       # offscreen end-to-end GUI exercise via the real worker
├── quality_check.py   # visual QA montage: original | white | magenta per image
├── ux_audit.py        # widget geometry / enable-state / teardown audit
├── install-desktop-entry.sh
└── fix-qt-libxcb.sh   # vendored libxcb-cursor.so.0 placement helper
tests/               # 22 tests, CPU-only, fake engines (no torch downloads)
```

## Data flow

```
image file ──► pipeline.process_file
                │  1. normalize: EXIF transpose, RGB convert, ~30 MP pixel cap
                │  2. engine.infer_matte(image, res)        → float32 alpha [0,1] @ original size
                │  3. refine.apply_refine(alpha, opts)      → tightened alpha
                │     (guided filter | closed-form matting | none)
                │  4. refine.fill_holes / feather / defringe (per options)
                │  5. compose.compose(fg, alpha, options)   → RGBA result
                │  6. compose.apply_shadow (optional)  →  export png/webp/jpg
                ▼
             output file
```

The GUI runs the same `process_file` inside a `QThread`-based `PipelineWorker`;
results stream back via queued signals (`item_done` / `item_failed`), so the
UI stays responsive during batches. Engines are cached in
`MainWindow._engines`, keyed by model key, so switching models in a session
reuses already-loaded weights.

## Matting engine design (`engine.py`)

- **Model catalogue** — `MODEL_CATALOG` maps a short key
  (`birefnet`, `rmbg2`) to a HF repo id, label, licence, and download size.
  Newer models are added there alone; CLI/GUI read the catalogue directly.
- **Lazy torch import** — `torch` is imported on first use so
  `--list-models`, packaging metadata, and most tests work without torch.
  Normalization is plain tensor math on purpose (no `torchvision.transforms`
  dependency at import time).
- **Resolution** — the long side is driven by `RES_PRESETS`
  (fast 768 / balanced 1024 / max 1536), rounded to a multiple of 32
  (window-attention constraint); logits are bicubically upsampled back to the
  *original* image size so the matte stays sharp.
- **Device & dtype strategy** — the engine never assumes fp32 checkpoints.
  Some checkpoints ship fp16 weights, so:
  - CUDA + `use_half` → model `.half()`, fp16 autocast, **input tensor cast to
    the loaded weights' dtype**;
  - CPU → model `.float()` (fp32), fp16 disabled;
  - a RuntimeError mentioning `Half` during inference triggers
    `_fallback_fp32()`: engine reload in fp32 and retry.
  This is why GPU/CPU paths stay numerically identical
  (measured: identical foreground coverage fractions).

## Refinement design (`refine.py`)

- `guided_refine` — fast edge cleanup, the default for every image size.
- `refine_closed_form` — pymatting's linear solve; best hair/glass edges at
  ~24 s/2.3 MP; **auto-skipped above ~4 MP** and the pipeline falls back to
  the guided filter.
- `fill_holes` — fills enclosed micro-holes (specular highlights, camera
  blowouts); hole detection bounds: `max(64 px, min(0.1 % of the image, 4096 px))`.
- `feather` / `decontaminate` — edge softening in pixels; defringe removes
  background colour spill on the alpha boundary.

## Composition design (`compose.py`)

- Background modes: transparent, solid colour, blurred original, custom image.
- `ShadowSpec` — colour, opacity, blur radius, vertical offset; the shadow is
  produced from the matte itself so it follows hair fill accurately.
- Encoders: PNG (RGBA, lossless), WebP, and JPG (flattened).

## Concurrency model

Both frontends call the same `process_file`. The CLI loops sequentially;
the GUI processes sequentially as well (one model instance at a time, one
GPU) but in a worker thread, keeping the UI thread free. Loading a second
model while one is cached creates a second engine entry; each engine owns its
model instance.

## Platform notes

- Qt ≥ 6.5's xcb plugin requires `libxcb-cursor.so.0`; when the system package
  is absent, `run.sh` exports `LD_LIBRARY_PATH` into `runtime-libs/` and the
  library is also copied into `PySide6/Qt/lib` (Qt RPATH) so desktop-launch
  paths work without sudo. GUI stderr is appended to
  `~/.cache/cutout-studio/gui.log`.
- Gated Hugging Face repos (RMBG-2.0) raise an actionable `RuntimeError`
  from `MattingEngine.load`: accept the licence, `huggingface-cli login`, retry.
