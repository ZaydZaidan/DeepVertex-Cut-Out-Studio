"""CLI for 3D product snapshots:  cutout-mesh MODEL [options]."""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cutout-mesh",
        description=(
            "Render web-ready product snapshots (front/back/left/right/top/bottom, "
            "3/4 hero views, optional turntable) from a 3D model — direct output for "
            "product pages / marketplaces. Formats: STL, OBJ, PLY, GLB/GLTF, STEP (optional)."
        ),
    )
    p.add_argument("model", help="3D model file (.stl, .obj, .ply, .glb, .gltf, .step)")
    p.add_argument("-o", "--out", default=None, help="output directory (default: ./<model>-shots)")
    p.add_argument("--views", default="standard",
                   help="standard | all | ortho | hero | comma list (front,back,hero-front-left,...) | turntable:N")
    p.add_argument("--bg", default="studio",
                   help="transparent | white | studio | dark | sunset | color")
    p.add_argument("--bg-color", default="#ffffff", help="colour for --bg color")
    p.add_argument("--shadow", choices=["auto", "on", "off"], default="auto",
                   help="soft contact shadow (auto: on except transparent/white)")
    p.add_argument("--reflection", choices=["auto", "on", "off"], default="auto",
                   help="floor reflection (auto: on for studio/dark/sunset/colour)")
    p.add_argument("--env-map", default=None,
                   help="optional equirect environment image (JPEG/PNG) to drive reflections")
    p.add_argument("--env-yaw", type=float, default=0.0,
                   help="rotate the environment horizontally, degrees")
    p.add_argument("--env-gain", type=float, default=1.0,
                   help="reflected-environment strength multiplier")
    p.add_argument("--size", type=int, default=1600, help="long-edge size in px (256..4096)")
    p.add_argument("--format", dest="fmt", choices=["png", "webp", "jpg"], default="png")
    p.add_argument("--fill", type=float, default=None,
                   help="framing fill (0..1). default 0.85 = Amazon main-image rule")
    p.add_argument("--no-sheet", dest="sheet", action="store_false", help="skip the contact sheet")
    return p


def main(argv: list[str] | None = None) -> int:
    from .mesh.shot import DEFAULT_FILL, render_snapshots

    args = build_parser().parse_args(argv)
    model = Path(args.model).expanduser()
    if not model.is_file():
        print(f"no such file: {model}", file=sys.stderr)
        return 2

    out_dir = (
        Path(args.out).expanduser() if args.out
        else model.parent / f"{model.stem}-shots"
    )
    try:
        outputs = render_snapshots(
            model,
            out_dir=out_dir,
            views_spec=args.views,
            bg=args.bg,
            bg_color=args.bg_color,
            size=args.size,
            fmt=args.fmt,
            shadow=args.shadow,
            reflection=args.reflection,
            env_map=args.env_map,
            env_yaw=math.radians(args.env_yaw),
            env_gain=args.env_gain,
            fill=args.fill if args.fill is not None else DEFAULT_FILL,
            sheet=args.sheet,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in outputs:
        print(f"ok  {path.name:34s} -> {path}")
    print(f"{len(outputs)} file(s) in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
