"""Build visual QA montages: original | cutout on white | cutout on magenta.

Usage: venv/bin/python scripts/quality_check.py OUTDIR IMAGE [IMAGE...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

PANEL_W = 640


def fit(img: Image.Image, w: int = PANEL_W) -> Image.Image:
    scale = w / img.width
    return img.resize((w, max(1, int(img.height * scale))), Image.LANCZOS)


def on_bg(cutout: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", cutout.size, color)
    base.paste(cutout, mask=cutout.split()[3] if cutout.mode == "RGBA" else None)
    return base


def main() -> int:
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    for raw in sys.argv[2:]:
        src = Path(raw)
        cut = outdir / f"{src.stem}-nobg.png"
        if not cut.exists():
            print(f"missing cutout for {src.name}")
            continue
        original = fit(Image.open(src).convert("RGB"))
        cutout = Image.open(cut)
        white = fit(on_bg(cutout, (255, 255, 255)))
        magenta = fit(on_bg(cutout, (255, 0, 255)))
        height = max(original.height, white.height, magenta.height)
        sheet = Image.new("RGB", (PANEL_W * 3 + 20, height + 8), (24, 24, 28))
        for i, panel in enumerate((original, white, magenta)):
            sheet.paste(panel, (i * (PANEL_W + 10) + 5, 4))
        out = outdir / f"qa_{src.stem}.jpg"
        sheet.save(out, quality=88)
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
