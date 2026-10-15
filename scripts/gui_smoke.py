"""Headless GUI smoke test: boots the real MainWindow offscreen, processes
images through the actual worker thread, and writes screenshots.

Usage: venv/bin/python scripts/gui_smoke.py OUTDIR IMAGE [IMAGE...]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from cutout.gui import MainWindow  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    outdir = Path(sys.argv[1])
    images = sys.argv[2:]
    outdir.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    win = MainWindow()
    win.outdir_edit.setText(str(outdir))
    win.resize(1240, 800)
    win.show()
    win._add_paths(images)
    app.processEvents()
    win.grab().save(str(outdir / "gui_before.png"))
    print("screenshot before:", outdir / "gui_before.png")

    win._start(only_selected=False)
    t0 = time.time()
    while win._thread is not None and time.time() - t0 < 900:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    win.grab().save(str(outdir / "gui_after.png"))
    print("screenshot after:", outdir / "gui_after.png")

    for path, res in win._results.items():
        print(f"ok {Path(path).name}: {res.width}x{res.height} {res.ms} ms fg={res.coverage:.1%} -> {res.out}")
    failed = win.file_list.count() - len(win._results)
    print(f"results: {len(win._results)} ok, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
