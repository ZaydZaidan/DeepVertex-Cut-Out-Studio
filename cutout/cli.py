"""Command-line interface for Cutout Studio (batch-friendly)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compose import ShadowSpec
from .engine import MODEL_CATALOG, RES_PRESETS, MattingEngine
from .pipeline import SUPPORTED_EXTS, ProcessOptions, process_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cutout",
        description="Local background remover (GPU-accelerated). "
        "Reads images, removes the background with a local matting model, "
        "and writes transparent PNG/WebP or flattened JPG results.",
    )
    p.add_argument("inputs", nargs="*", help="image files or directories")
    p.add_argument("--model", choices=sorted(MODEL_CATALOG), default="birefnet",
                   help="matting model (default: birefnet)")
    p.add_argument("--quality", choices=sorted(RES_PRESETS), default="balanced",
                   help="inference resolution preset (default: balanced / 1024)")
    p.add_argument("--refine", choices=["none", "guided", "matting"], default="guided",
                   help="alpha refinement: guided (fast) or closed-form matting (slow, best edges)")
    p.add_argument("--feather", type=float, default=0.0, help="edge softness in pixels")
    p.add_argument("--defringe", action="store_true", help="remove background colour fringe")
    p.add_argument("--no-fill-holes", dest="fill_holes", action="store_false",
                   help="do not fill small holes inside the subject")
    p.add_argument("--bg", default="transparent",
                   help="background: transparent | color | blur | <image path>")
    p.add_argument("--bg-color", default="#ffffff", help="background colour for --bg color")
    p.add_argument("--blur-radius", type=float, default=24.0, help="blur radius for --bg blur")
    p.add_argument("--shadow", action="store_true", help="add a drop shadow")
    p.add_argument("--shadow-color", default="#000000")
    p.add_argument("--shadow-opacity", type=float, default=0.35)
    p.add_argument("--shadow-blur", type=float, default=24.0)
    p.add_argument("--shadow-offset-y", type=float, default=18.0, help="shadow vertical offset (px)")
    p.add_argument("--format", dest="fmt", choices=["png", "webp", "jpg"], default="png")
    p.add_argument("--out", "-o", default=None, help="output directory (default: beside each source)")
    p.add_argument("--suffix", default="-nobg", help="output filename suffix")
    p.add_argument("--cpu", action="store_true", help="force CPU inference")
    p.add_argument("--prefetch-model", action="store_true",
                   help="download/load the model and exit (cache warm-up)")
    p.add_argument("--list-models", action="store_true", help="show available models and exit")
    return p


def resolve_inputs(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in SUPPORTED_EXTS))
        elif p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            files.append(p)
        else:
            print(f"skip (unsupported or missing): {p}", file=sys.stderr)
    return files


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_models:
        for key, info in MODEL_CATALOG.items():
            print(f"{key:10s} {info.label:34s} license={info.license:34s} download={info.approx_download}")
        return 0

    engine = MattingEngine(model=args.model, device="cpu" if args.cpu else None)
    if args.prefetch_model:
        print(f"prefetching {engine.info.repo} ...")
        engine.load()
        print(f"model ready: {engine.description()}")
        return 0

    files = resolve_inputs(args.inputs)
    if not files:
        build_parser().print_help()
        return 2

    bg_mode = "transparent"
    bg_image = None
    blob = args.bg
    if blob in ("transparent", "color", "blur"):
        bg_mode = blob
    else:
        bg_mode, bg_image = "image", str(Path(blob).expanduser())

    opts = ProcessOptions(
        model=args.model,
        res_preset=args.quality,
        refine=args.refine,
        fill_holes=args.fill_holes,
        feather_px=args.feather,
        defringe=args.defringe,
        bg_mode=bg_mode,
        bg_color=args.bg_color,
        bg_image=bg_image,
        blur_radius=args.blur_radius,
        shadow=ShadowSpec(
            enabled=args.shadow,
            color=args.shadow_color,
            opacity=args.shadow_opacity,
            blur=args.shadow_blur,
            offset_y=args.shadow_offset_y,
        ),
        out_format=args.fmt,
        suffix=args.suffix,
    )

    print(f"loading {engine.info.label} ...")
    engine.load()
    print(f"engine: {engine.description()}")

    failures = 0
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name} ...", end=" ", flush=True)
        try:
            res = process_file(path, opts, engine, out_dir=args.out)
            print(f"ok {res.ms} ms, {res.width}x{res.height}, fg {res.coverage:.1%} -> {res.out}")
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            failures += 1
            print(f"FAILED: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
