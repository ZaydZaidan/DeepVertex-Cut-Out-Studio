"""3D Product Snapshot dialog — STEP/STL/OBJ/GLB/PGL -> web-ready shots.

Invoked from the GUI *Process* menu ("3D Product Snapshot…") and File menu
(drag & drop of model files onto the main window is routed here too when the
file has a 3D extension).
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from cutout.mesh.shot import render_snapshots

FORMATS_3D = (
    "STL / OBJ / PLY / GLB / GLTF (trimesh),  STEP (optional [step] extra)"
)
OUTPUT_FORMATS = ("png", "webp", "jpg")


class MeshSnapshotWorker(QObject):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, path: str, out_dir: str, opts: dict) -> None:
        super().__init__()
        self.path = path
        self.out_dir = out_dir
        self.opts = opts

    def run(self) -> None:
        try:
            outputs = render_snapshots(self.path, self.out_dir, **self.opts)
            self.done.emit([str(p) for p in outputs])
        except Exception as exc:  # noqa: BLE001 - dialog-level error report
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MeshSnapshotDialog(QDialog):
    """Pick a 3D model, choose views/background, render snapshots."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("3D Product Snapshot")
        self.setModal(False)
        self.resize(560, 380)
        self._thread: QThread | None = None
        self._worker: MeshSnapshotWorker | None = None

        # ------------------------------------------------------------- model
        model_row = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText(f"({FORMATS_3D})")
        self.model_edit.setDragEnabled(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_model)
        model_row.addWidget(self.model_edit, 1)
        model_row.addWidget(browse)

        # ------------------------------------------------------------- views
        self.cb_ortho = QCheckBox("Six CAD views (front/back/left/right/top/bottom)")
        self.cb_ortho.setChecked(True)
        self.cb_hero = QCheckBox("Hero 3/4 views (front-left / front-right / rear)")
        self.cb_hero.setChecked(True)
        spin_row = QHBoxLayout()
        spin_row.addWidget(QLabel("Turntable steps (0 = off):"))
        self.turntable_spin = QSpinBox()
        self.turntable_spin.setRange(0, 72)
        self.turntable_spin.setValue(0)
        spin_row.addWidget(self.turntable_spin)
        spin_row.addStretch(1)
        views_box = QGroupBox("Views")
        v = QVBoxLayout(views_box)
        v.addWidget(self.cb_ortho)
        v.addWidget(self.cb_hero)
        v.addLayout(spin_row)

        # -------------------------------------------------------- background
        form = QFormLayout()
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(
            ["studio", "transparent", "white", "dark", "sunset", "color"]
        )
        self.bg_color_edit = QLineEdit("#ffffff")
        self.shadow_combo = QComboBox()
        self.shadow_combo.addItems(["auto", "on", "off"])
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(OUTPUT_FORMATS)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(256, 4096)
        self.size_spin.setValue(1600)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("(default: <model>-shots next to the model)")
        out_row = QHBoxLayout()
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(out_browse)

        form.addRow("Background:", self.bg_combo)
        form.addRow("Background colour:", self.bg_color_edit)
        form.addRow("Shadow:", self.shadow_combo)
        form.addRow("Output format:", self.fmt_combo)
        form.addRow("Image size (px):", self.size_spin)
        form.addRow("Output folder:", out_row)

        button_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.render_btn = QPushButton("Render snapshots")
        self.render_btn.clicked.connect(self._render)
        button_row.addWidget(self.status_label, 1)
        button_row.addWidget(self.render_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(model_row)
        layout.addWidget(views_box)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addLayout(button_row)

    # --------------------------------------------------------------- helpers
    def _views_spec(self) -> str:
        parts = []
        if self.cb_ortho.isChecked():
            parts.append("ortho")
        if self.cb_hero.isChecked():
            parts.append("hero")
        steps = self.turntable_spin.value()
        if steps:
            parts.append(f"turntable:{steps}")
        return ",".join(parts) or "hero"

    def _browse_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a 3D model",
            "",
            f"3D models ({' '.join(['*.stl *.obj *.ply *.glb *.gltf *.step *.stp'])})",
        )
        if path:
            self.model_edit.setText(path)
            stem = Path(path).stem + "-shots"
            self.out_edit.setText(str(Path(path).parent / stem))

    def _browse_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self.out_edit.setText(d)

    # ---------------------------------------------------------------- render
    def _render(self) -> None:
        model = self.model_edit.text().strip()
        if not model or not Path(model).is_file():
            self.status_label.setText("Choose a valid 3D model file first.")
            return
        opts = dict(
            views_spec=self._views_spec(),
            bg=self.bg_combo.currentText(),
            bg_color=self.bg_color_edit.text().strip() or "#ffffff",
            size=self.size_spin.value(),
            fmt=self.fmt_combo.currentText(),
            shadow=self.shadow_combo.currentText(),
        )
        out_dir = self.out_edit.text().strip() or str(Path(model).parent / (Path(model).stem + "-shots"))
        self.render_btn.setEnabled(False)
        self.status_label.setText("Rendering …")
        self._thread = QThread(self)
        self._worker = MeshSnapshotWorker(model, out_dir, opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(lambda msg: (self.status_label.setText(msg), self.render_btn.setEnabled(True)))
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_done(self, outputs: list) -> None:
        self.render_btn.setEnabled(True)
        self.status_label.setText(f"{len(outputs)} file(s) written — see the status log.")
        for line in outputs:
            self.status_label.setText(str(self.status_label.text()) + f"  ·  {Path(line).name}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)
        event.accept()
