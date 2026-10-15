"""Capture a screenshot of the 3D Product Snapshot dialog for the README.

Usage: venv/bin/python scripts/capture_mesh_dialog.py MODEL OUT.png
           [--out-dir DIR] [--turntable N]

Fills the dialog with the given model path (and the derived shots folder),
then grabs it — no render is started, so it is safe to run anywhere. Use the
real display like ux_audit.py (`QT_QPA_PLATFORM=xcb DISPLAY=:1 ...`) so the
shot matches the other repo screenshots; falls back to offscreen when no
platform is configured.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from cutout.snapshot_dialog import MeshSnapshotDialog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture a screenshot of the 3D Product Snapshot dialog."
    )
    parser.add_argument("model", type=Path, help="3D model file shown in the dialog")
    parser.add_argument("out_png", type=Path, help="path of the saved screenshot")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="value for the output-folder field (default: <model>-shots)",
    )
    parser.add_argument(
        "--turntable",
        type=int,
        default=0,
        help="turntable steps to show in the dialog (0 = off, as designed)",
    )
    parser.add_argument("--width", type=int, default=600, help="dialog width")
    parser.add_argument("--height", type=int, default=420, help="dialog height")
    args = parser.parse_args()

    app = QApplication([])
    dialog = MeshSnapshotDialog(None)
    dialog.model_edit.setText(str(args.model))
    out_dir = args.out_dir or args.model.parent / (args.model.stem + "-shots")
    dialog.out_edit.setText(str(out_dir))
    dialog.turntable_spin.setValue(args.turntable)
    dialog.resize(args.width, args.height)
    dialog.show()
    for _ in range(3):
        app.processEvents()

    # Marketing shot: no default-button ring / focus highlight anywhere.
    # (autoDefault buttons draw the platform ring in dialogs even without
    # focus — 188 orange pixels on the Browse button; clearing focus alone
    # does NOT remove it.)
    for button in dialog.findChildren(QPushButton):
        button.setAutoDefault(False)
        button.setDefault(False)
    focused = app.focusWidget()
    if focused is not None:
        focused.clearFocus()
    app.processEvents()

    args.out_png.parent.mkdir(parents=True, exist_ok=True)
    if not dialog.grab().save(str(args.out_png)):
        print(f"FAILED to save {args.out_png}")
        return 1
    print(f"saved {args.out_png} ({args.out_png.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
