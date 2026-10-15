"""Automated UI/UX audit for DeepVertex Cut-Out Studio.

Measures layout spacing between settings groups and rows, checks for widget
overflow / clipped controls / truncated combo text at the minimum window size,
verifies control enable-state logic, and runs a real batch through the worker
thread while capturing screenshots.

Usage: venv/bin/python scripts/ux_audit.py OUTDIR IMAGE [IMAGE...]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QFormLayout, QGroupBox, QScrollArea, QWidget  # noqa: E402

from cutout.gui import GAP, GROUP_GAP, MainWindow  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    tag = "ok  " if condition else "FAIL"
    if not condition:
        FAILURES.append(message)
    print(f"  [{tag}] {message}")


def vertical_gaps(widgets: list[QWidget]) -> list[int]:
    positioned = []
    for w in widgets:
        if not w.isVisible():
            continue
        top = w.mapToGlobal(w.rect().topLeft()).y()
        bottom = w.mapToGlobal(w.rect().bottomLeft()).y()
        positioned.append((top, bottom))
    positioned.sort()
    return [positioned[i + 1][0] - positioned[i][1] for i in range(len(positioned) - 1)]


def audit_geometry(win: MainWindow, label: str) -> None:
    print(f"--- geometry audit @ {label} ---")
    scroll: QScrollArea = win.findChild(QScrollArea)
    content = scroll.widget()
    print(f"  window {win.width()}x{win.height()} | viewport {scroll.viewport().width()}px "
          f"| content min-width {content.minimumSizeHint().width()}px")

    groups = content.findChildren(QGroupBox)
    gaps = vertical_gaps(groups)
    print(f"  group-to-group gaps: {gaps}")
    check(not gaps or min(gaps) >= GROUP_GAP - 4, f"group spacing >= {GROUP_GAP - 4}px ({gaps})")

    for group in groups:
        form = group.layout()
        if not isinstance(form, QFormLayout):
            continue
        row_tops: list[int] = []
        row_bottoms: list[int] = []
        for i in range(form.rowCount()):
            widgets = []
            for role in (QFormLayout.LabelRole, QFormLayout.FieldRole, QFormLayout.SpanningRole):
                item = form.itemAt(i, role)
                widget = item.widget() if item else None
                if isinstance(widget, QWidget) and widget.isVisible():
                    widgets.append(widget)
            if not widgets:
                continue
            tops = [w.mapToGlobal(w.rect().topLeft()).y() for w in widgets]
            bottoms = [w.mapToGlobal(w.rect().bottomLeft()).y() for w in widgets]
            row_tops.append(min(tops))
            row_bottoms.append(max(bottoms))
        order = sorted(range(len(row_tops)), key=lambda k: row_tops[k])
        form_gaps = [
            row_tops[order[i + 1]] - row_bottoms[order[i]] for i in range(len(order) - 1)
        ]
        if form_gaps:
            print(f"    {group.title()!r}: row gaps {form_gaps}")
            check(min(form_gaps) >= GAP, f"{group.title()} row spacing >= {GAP}px (min {min(form_gaps)})")

    check(not scroll.horizontalScrollBar().isVisible(), "no horizontal scrollbar in settings panel")

    overflowing = []
    for child in content.findChildren(QWidget):
        if child is content:
            continue
        right = child.mapTo(content, child.rect().bottomRight()).x()
        if right > content.width() + 2:
            overflowing.append((type(child).__name__, right, content.width()))
    check(not overflowing, f"no widget overflows the settings panel ({overflowing[:3]})")

    for name, box in (
        ("model", win.model_combo), ("quality", win.quality_combo), ("refine", win.refine_combo),
        ("background", win.bg_combo), ("format", win.format_combo),
    ):
        needed = box.fontMetrics().horizontalAdvance(box.currentText()) + 44
        check(box.width() >= needed, f"combo {name!r} not truncated ({box.width()} >= {needed}px)")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    images = sys.argv[2:]

    app = QApplication([])
    win = MainWindow()
    win.resize(win.width(), win.height())
    win.show()
    win.outdir_edit.setText(str(outdir))
    win._add_paths(images)
    app.processEvents()
    win.grab().save(str(outdir / "ux_before.png"))

    audit_geometry(win, f"default {win.width()}x{win.height()}")
    win.resize(win.minimumSize().width(), win.minimumSize().height())
    app.processEvents()
    audit_geometry(win, f"minimum {win.width()}x{win.height()}")

    print("--- control-state logic ---")
    win.shadow_check.setChecked(True)
    app.processEvents()
    check(win.shadow_opacity.isEnabled(), "shadow controls enable when checkbox is on")
    win.shadow_check.setChecked(False)
    app.processEvents()
    check(not win.shadow_opacity.isEnabled(), "shadow controls disable when checkbox is off")
    for idx, mode, expect in ((0, "transparent", (False, False, False)), (1, "colour", (True, False, False)),
                              (2, "blur", (False, True, False)), (3, "image", (False, False, True))):
        win.bg_combo.setCurrentIndex(idx)
        app.processEvents()
        got = (win.color_btn.isEnabled(), win.blur_spin.isEnabled(), win.bg_image_btn.isEnabled())
        check(got == expect, f"background mode {mode!r} enables {expect} (got {got})")
    win.bg_combo.setCurrentIndex(0)

    print("--- about dialog ---")
    box = win._about_box()
    box.show()
    app.processEvents()
    box.grab().save(str(outdir / "ux_about.png"))
    text = box.text()
    check("DeepVertex Cut-Out Studio" in text and "MIT" in text, "about dialog contains name and model licences")
    box.close()

    print("--- real batch through the worker thread ---")
    win.resize(1280, 820)
    win._start(only_selected=False)
    t0 = time.time()
    while win._thread is not None and time.time() - t0 < 900:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    win.grab().save(str(outdir / "ux_after.png"))
    check(len(win._results) == len(images), f"processed {len(win._results)}/{len(images)} images")
    check(win._thread is None and win._worker is None, "worker thread torn down after batch")
    check(win.process_btn.isEnabled() and win.process_all_btn.isEnabled(), "action buttons re-enabled after batch")

    print("--- result inspection ---")
    for path, res in win._results.items():
        check(res.out.exists(), f"output written: {res.out.name}")
        print(f"    {Path(path).name}: {res.width}x{res.height} {res.ms} ms fg={res.coverage:.1%}")

    print()
    if FAILURES:
        print(f"AUDIT RESULT: {len(FAILURES)} failure(s)")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("AUDIT RESULT: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
