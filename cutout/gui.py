"""DeepVertex Cut-Out Studio — PySide6 desktop application.

A local, GPU-accelerated AI background remover modelled on the remove.bg web
workflow reconstructed in ``docs/RECON_REPORT.md``: pick images, remove
backgrounds, adjust the result (backgrounds / shadow / edge quality) and
export.  Everything runs on this machine; no uploads, no accounts.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .compose import ShadowSpec
from .engine import MODEL_CATALOG, MattingEngine
from .pipeline import SUPPORTED_EXTS, ProcessOptions, ProcessResult, process_file

APP_NAME = "DeepVertex Cut-Out Studio"
REPO_URL = "https://github.com/ZaydZaidan/DeepVertex-Cut-Out-Studio"
IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"

# ---- layout spacing system (8 px base unit, keeps the UI from feeling crowded)
MARGIN = 14       # window / panel margins
GAP = 10          # space between related controls
GROUP_GAP = 18    # space between groups / sections


def _tune_form(form: QFormLayout) -> None:
    """Apply consistent breathing room to a settings form."""
    form.setContentsMargins(MARGIN + 2, 22, MARGIN + 2, 16)
    form.setVerticalSpacing(12)
    form.setHorizontalSpacing(MARGIN + 2)

STYLE = """
QMainWindow, QWidget { background: #16181d; color: #e8eaed; font-size: 13px; }
QMenuBar { background: #16181d; }
QMenuBar::item:selected { background: #2a2e35; }
QMenu { background: #1e2127; border: 1px solid #2a2e35; }
QMenu::item:selected { background: #2f3b52; }
QGroupBox { border: 1px solid #2a2e35; border-radius: 8px; margin-top: 10px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0a6; }
QPushButton { background: #262b33; border: 1px solid #3a3f47; border-radius: 7px; padding: 7px 14px; }
QPushButton:hover { background: #303743; }
QPushButton:disabled { color: #7b828c; background: #1b1e24; }
QPushButton#primary { background: #2563eb; border-color: #2563eb; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #1f2c4d; border-color: #1f2c4d; color: #7a86a0; }
QComboBox, QLineEdit, QDoubleSpinBox, QSpinBox {
    background: #1e2127; border: 1px solid #454b57; border-radius: 7px; padding: 4px 8px;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {
    background: #262b33; width: 16px; border-left: 1px solid #454b57;
}
QCheckBox::indicator {
    width: 15px; height: 15px; border: 1px solid #4a5160; border-radius: 4px; background: #1e2127;
}
QCheckBox::indicator:checked { background: #2563eb; border-color: #2563eb; }
QRadioButton::indicator {
    width: 14px; height: 14px; border-radius: 8px; border: 1px solid #4a5160; background: #1e2127;
}
QRadioButton::indicator:checked { background: #2563eb; border: 3px solid #16181d; }
QRadioButton:checked { color: #ffffff; font-weight: 600; }
QDoubleSpinBox:disabled, QSpinBox:disabled, QLineEdit:disabled, QComboBox:disabled {
    color: #6b7280; border-color: #2c313a; background: #191c21;
}
QComboBox QAbstractItemView { background: #1e2127; selection-background-color: #2f3b52; }
QListWidget { background: #1a1d23; border: 1px solid #2a2e35; border-radius: 8px; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background: #2f3b52; }
QProgressBar { background: #1e2127; border: 1px solid #2a2e35; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
QRadioButton { padding: 4px; }
QScrollArea { border: none; }
QSplitter::handle { background: #22262d; }
"""


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def make_checker_tile() -> QPixmap:
    pm = QPixmap(24, 24)
    pm.fill(QColor("#33383f"))
    p = QPainter(pm)
    p.fillRect(0, 0, 12, 12, QColor("#2b3037"))
    p.fillRect(12, 12, 12, 12, QColor("#2b3037"))
    p.end()
    return pm


class PreviewCanvas(QWidget):
    """Checkered preview with fit-to-window scaling and original/result toggle."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._checker = make_checker_tile()
        self._original: QPixmap | None = None
        self._result: QPixmap | None = None
        self._show_result = True
        self._cache_key: tuple | None = None
        self._cache_scaled: QPixmap | None = None
        self.setMinimumSize(QSize(420, 320))

    def set_original(self, image: Image.Image | None) -> None:
        self._original = pil_to_pixmap(image) if image is not None else None
        self._invalidate()

    def set_result(self, image: Image.Image | None) -> None:
        self._result = pil_to_pixmap(image) if image is not None else None
        self._invalidate()

    def set_show_result(self, show_result: bool) -> None:
        self._show_result = show_result
        self._invalidate()

    def _invalidate(self) -> None:
        self._cache_key = None
        self.update()

    def _current(self) -> QPixmap | None:
        return self._result if self._show_result else self._original

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QBrush(self._checker))
        pm = self._current()
        if pm is None:
            painter.setPen(QColor("#9aa0a6"))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "No image yet\nDrag & drop images into this window",
            )
            return
        target = self.size() * 0.97
        key = (target.width(), target.height(), self._show_result, id(pm))
        if self._cache_key != key:
            self._cache_scaled = pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._cache_key = key
        scaled = self._cache_scaled
        assert scaled is not None
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class PipelineWorker(QObject):
    """Sequential processing worker (one image at a time, GPU-friendly)."""

    progress = Signal(int, int, str)
    item_done = Signal(object)
    item_failed = Signal(str, str)
    finished = Signal()

    def __init__(
        self, engine: MattingEngine, opts: ProcessOptions, paths: list[str], out_dir: str | None
    ) -> None:
        super().__init__()
        self.engine = engine
        self.opts = opts
        self.paths = paths
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            if not self.engine.loaded:
                self.progress.emit(0, len(self.paths), "Loading model (first run may download weights)…")
                self.engine.load()
            for i, path in enumerate(self.paths):
                self.progress.emit(i, len(self.paths), f"Processing {Path(path).name}…")
                try:
                    result = process_file(path, self.opts, self.engine, out_dir=self.out_dir)
                    self.item_done.emit(result)
                except Exception as exc:  # noqa: BLE001 - report per-file failures in UI
                    traceback.print_exc()
                    self.item_failed.emit(path, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — AI Background Remover")
        self.resize(1320, 860)
        self.setMinimumSize(1140, 740)
        self.setAcceptDrops(True)

        self._engines: dict[str, MattingEngine] = {}
        self._results: dict[str, ProcessResult] = {}
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

        self._build_menu()
        self._build_ui()
        self.setStyleSheet(STYLE)

    # ----------------------------------------------------------------- menu
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_add = QAction("&Add Images…", self)
        act_add.setShortcut(QKeySequence("Ctrl+O"))
        act_add.triggered.connect(self._add_files)
        act_clear = QAction("&Clear List", self)
        act_clear.triggered.connect(self._clear_files)
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addActions([act_add, act_clear])
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        process_menu = self.menuBar().addMenu("&Process")
        act_selected = QAction("Process &Selected", self)
        act_selected.setShortcut(QKeySequence("Ctrl+Return"))
        act_selected.triggered.connect(lambda: self._start(only_selected=True))
        act_all = QAction("Process A&ll", self)
        act_all.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        act_all.triggered.connect(lambda: self._start(only_selected=False))
        process_menu.addActions([act_selected, act_all])

        help_menu = self.menuBar().addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._show_about)
        act_repo = QAction("Open &Repository", self)
        act_repo.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        help_menu.addActions([act_about, act_repo])

    def _about_box(self) -> QMessageBox:
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<b>{APP_NAME}</b> v{__version__}<br><br>"
            "Local, GPU-accelerated AI background remover.<br>"
            "No uploads — images never leave this machine.<br><br>"
            "<b>Models</b><br>"
            "• BiRefNet-general — MIT license<br>"
            "• RMBG-2.0 — BRIA non-commercial license (gated: requires Hugging Face login &amp; licence accept)<br><br>"
            f'<a href="{REPO_URL}">{REPO_URL}</a>'
        )
        return box

    def _show_about(self) -> None:
        self._about_box().exec()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # ---- files panel
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(MARGIN, MARGIN, GAP, MARGIN)
        left_layout.setSpacing(GAP)
        left_layout.addWidget(QLabel("<b>Images</b>"))
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.file_list, 1)
        row = QHBoxLayout()
        row.setSpacing(GAP)
        add_btn = QPushButton("Add…")
        add_btn.clicked.connect(self._add_files)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_files)
        for b in (add_btn, remove_btn, clear_btn):
            row.addWidget(b)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        # ---- preview
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(GAP, MARGIN, GAP, MARGIN)
        center_layout.setSpacing(GAP + 2)
        top = QHBoxLayout()
        self.radio_original = QRadioButton("Original")
        self.radio_result = QRadioButton("Result")
        self.radio_result.setChecked(True)
        self.radio_original.toggled.connect(self._refresh_preview)
        top.addWidget(self.radio_original)
        top.addWidget(self.radio_result)
        top.addStretch(1)
        self.preview_info = QLabel("—")
        self.preview_info.setStyleSheet("color:#9aa0a6;")
        top.addWidget(self.preview_info)
        center_layout.addLayout(top)
        self.canvas = PreviewCanvas()
        center_layout.addWidget(self.canvas, 1)
        splitter.addWidget(center)

        # ---- settings panel
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right = QWidget()
        right.setMinimumWidth(360)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(MARGIN, MARGIN, MARGIN + 6, MARGIN + 4)
        right_layout.setSpacing(GROUP_GAP)

        g_model = QGroupBox("Model && edge quality")
        f_model = QFormLayout(g_model)
        _tune_form(f_model)
        self.model_combo = QComboBox()
        short_labels = {"birefnet": "BiRefNet-general", "rmbg2": "RMBG-2.0 (NC)"}
        for key, info in MODEL_CATALOG.items():
            self.model_combo.addItem(short_labels.get(key, info.label), key)
        f_model.addRow("Model", self.model_combo)
        self.quality_combo = QComboBox()
        for label, key in (
            ("Fast (768 px)", "fast"),
            ("Balanced (1024 px)", "balanced"),
            ("Maximum (1536 px)", "max"),
        ):
            self.quality_combo.addItem(label, key)
        self.quality_combo.setCurrentIndex(1)
        f_model.addRow("Quality", self.quality_combo)
        self.refine_combo = QComboBox()
        for label, key in (
            ("Guided (fast)", "guided"),
            ("Matting (best, slow)", "matting"),
            ("None", "none"),
        ):
            self.refine_combo.addItem(label, key)
        f_model.addRow("Alpha refinement", self.refine_combo)
        self.feather_spin = QDoubleSpinBox()
        self.feather_spin.setRange(0.0, 5.0)
        self.feather_spin.setSingleStep(0.5)
        self.feather_spin.setValue(0.0)
        f_model.addRow("Edge feather (px)", self.feather_spin)
        self.defringe_check = QCheckBox("Defringe: clean colour fringe")
        f_model.addRow(self.defringe_check)
        self.fillholes_check = QCheckBox("Fill small holes in subject")
        self.fillholes_check.setChecked(True)
        f_model.addRow(self.fillholes_check)
        right_layout.addWidget(g_model)

        g_bg = QGroupBox("Background")
        f_bg = QFormLayout(g_bg)
        _tune_form(f_bg)
        self.bg_combo = QComboBox()
        for label, key in (
            ("Transparent", "transparent"),
            ("Solid colour", "color"),
            ("Blur original", "blur"),
            ("Custom image…", "image"),
        ):
            self.bg_combo.addItem(label, key)
        self.bg_combo.currentIndexChanged.connect(self._update_bg_widgets)
        f_bg.addRow("Mode", self.bg_combo)
        self.color_btn = QPushButton("#ffffff")
        self.color_btn.clicked.connect(self._pick_color)
        f_bg.addRow("Colour", self.color_btn)
        self.blur_spin = QDoubleSpinBox()
        self.blur_spin.setRange(0, 120)
        self.blur_spin.setValue(24)
        f_bg.addRow("Blur radius", self.blur_spin)
        self.bg_image_btn = QPushButton("Choose image…")
        self.bg_image_btn.clicked.connect(self._pick_bg_image)
        f_bg.addRow(self.bg_image_btn)
        self._bg_image_path: str | None = None
        right_layout.addWidget(g_bg)

        g_shadow = QGroupBox("Shadow")
        f_shadow = QFormLayout(g_shadow)
        _tune_form(f_shadow)
        self.shadow_check = QCheckBox("Enable drop shadow")
        f_shadow.addRow(self.shadow_check)
        self.shadow_color_btn = QPushButton("#000000")
        self.shadow_color_btn.clicked.connect(self._pick_shadow_color)
        f_shadow.addRow("Colour", self.shadow_color_btn)
        self.shadow_opacity = QDoubleSpinBox()
        self.shadow_opacity.setRange(0.0, 1.0)
        self.shadow_opacity.setSingleStep(0.05)
        self.shadow_opacity.setValue(0.35)
        f_shadow.addRow("Opacity", self.shadow_opacity)
        self.shadow_blur = QDoubleSpinBox()
        self.shadow_blur.setRange(0, 120)
        self.shadow_blur.setValue(24)
        f_shadow.addRow("Blur", self.shadow_blur)
        self.shadow_offset = QDoubleSpinBox()
        self.shadow_offset.setRange(-200, 200)
        self.shadow_offset.setValue(18)
        f_shadow.addRow("Offset Y (px)", self.shadow_offset)
        self.shadow_check.toggled.connect(self._update_shadow_widgets)
        self._update_shadow_widgets(False)
        right_layout.addWidget(g_shadow)

        g_out = QGroupBox("Output")
        f_out = QFormLayout(g_out)
        _tune_form(f_out)
        self.format_combo = QComboBox()
        for label, key in (
            ("PNG (transparent)", "png"),
            ("WebP lossless", "webp"),
            ("JPG (white)", "jpg"),
        ):
            self.format_combo.addItem(label, key)
        f_out.addRow("Format", self.format_combo)
        self.suffix_edit = QLineEdit("-nobg")
        f_out.addRow("Filename suffix", self.suffix_edit)
        self.outdir_edit = QLineEdit("")
        self.outdir_edit.setPlaceholderText("(empty = beside each source image)")
        out_row = QHBoxLayout()
        out_row.addWidget(self.outdir_edit, 1)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._pick_outdir)
        out_row.addWidget(browse_btn)
        wrap = QWidget()
        wrap.setLayout(out_row)
        f_out.addRow("Output folder", wrap)
        self.open_out_btn = QPushButton("Open output folder")
        self.open_out_btn.clicked.connect(self._open_output_dir)
        f_out.addRow(self.open_out_btn)
        right_layout.addWidget(g_out)

        right_layout.addStretch(1)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)

        splitter.setSizes([250, 650, 380])

        # ---- bottom bar
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(MARGIN, GAP, MARGIN, MARGIN)
        bottom_layout.setSpacing(MARGIN)
        self.process_btn = QPushButton("Process Selected")
        self.process_btn.setObjectName("primary")
        self.process_btn.clicked.connect(lambda: self._start(only_selected=True))
        self.process_all_btn = QPushButton("Process All")
        self.process_all_btn.setObjectName("primary")
        self.process_all_btn.clicked.connect(lambda: self._start(only_selected=False))
        self.progress = QProgressBar()
        self.progress.setFixedHeight(18)
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color:#9aa0a6;")
        bottom_layout.addWidget(self.process_btn)
        bottom_layout.addWidget(self.process_all_btn)
        bottom_layout.addWidget(self.progress, 1)
        bottom_layout.addWidget(self.status_label)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter, 1)
        root.addWidget(bottom)
        self.setCentralWidget(container)

        for combo in (self.model_combo, self.quality_combo, self.refine_combo, self.bg_combo, self.format_combo):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        for spin in (self.feather_spin, self.blur_spin, self.shadow_opacity, self.shadow_blur, self.shadow_offset):
            spin.setMaximumWidth(120)

        # tooltips — first-time users should not need to open the README
        self.model_combo.setToolTip(
            "BiRefNet (MIT) is the default — downloads automatically on first use.\n"
            "RMBG-2.0 is better on some products but has a non-commercial licence "
            "and is gated: accept it at huggingface.co/briaai/RMBG-2.0, then run "
            "`huggingface-cli login`."
        )
        self.quality_combo.setToolTip("Network input resolution — higher keeps more fine detail, slower.")
        self.refine_combo.setToolTip("Guided: fast edge cleanup. Matting: best hair/glass edges, adds ~20 s per image (auto-skipped above ~4 MP).")
        self.feather_spin.setToolTip("Soften the cutout edge by this many pixels (0 = off).")
        self.defringe_check.setToolTip("Remove background colour bleeding from edge pixels.")
        self.fillholes_check.setToolTip("Restore small holes inside the subject (bright highlights misread as background).")
        self.bg_combo.setToolTip("What is placed behind the subject.")
        self.color_btn.setToolTip("Click to pick the background colour.")
        self.blur_spin.setToolTip("Blur radius applied to the original photo when used as background.")
        self.bg_image_btn.setToolTip("Use your own image as background (cover-fit).")
        self.shadow_check.setToolTip("Composite a soft drop shadow under the subject.")
        self.shadow_opacity.setToolTip("Shadow strength (0 = invisible, 1 = solid).")
        self.format_combo.setToolTip("PNG/WebP keep transparency; JPG flattens onto white.")
        self.suffix_edit.setToolTip("Appended to each output filename, e.g. photo-nobg.png.")
        self.outdir_edit.setToolTip("Where results are written. Empty = next to each source image.")

        self._update_bg_widgets()

    def _update_shadow_widgets(self, enabled: bool) -> None:
        for widget in (self.shadow_color_btn, self.shadow_opacity, self.shadow_blur, self.shadow_offset):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------- helpers
    def _update_bg_widgets(self) -> None:
        mode = self.bg_combo.currentData()
        self.color_btn.setEnabled(mode == "color")
        self.blur_spin.setEnabled(mode == "blur")
        self.bg_image_btn.setEnabled(mode == "image")

    def _pick_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        col = QColorDialog.getColor(QColor(self.color_btn.text()), self, "Pick background colour")
        if col.isValid():
            self.color_btn.setText(col.name())

    def _pick_shadow_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        col = QColorDialog.getColor(QColor(self.shadow_color_btn.text()), self, "Pick shadow colour")
        if col.isValid():
            self.shadow_color_btn.setText(col.name())

    def _pick_bg_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose background image", "", IMAGE_FILTER)
        if path:
            self._bg_image_path = path
            self.bg_image_btn.setText(Path(path).name)

    def _pick_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.outdir_edit.setText(d)

    def _open_output_dir(self) -> None:
        target = self.outdir_edit.text().strip()
        if not target:
            items = self.file_list.selectedItems() or [
                self.file_list.item(i) for i in range(self.file_list.count())
            ]
            for item in items:
                res = self._results.get(item.data(Qt.UserRole))
                if res:
                    target = str(res.out.parent)
                    break
        if target and Path(target).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    # --------------------------------------------------------------- files
    def _add_paths(self, paths: list[str]) -> None:
        existing = {self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())}
        for raw in paths:
            p = Path(raw)
            if p.suffix.lower() not in SUPPORTED_EXTS or str(p) in existing:
                continue
            try:
                with Image.open(p) as im:
                    mp = (im.width * im.height) / 1e6
                    dims = f"{im.width}×{im.height}"
            except Exception:  # noqa: BLE001
                continue
            item = QListWidgetItem(f"{p.name}\n  {dims} · {mp:.1f} MP")
            item.setData(Qt.UserRole, str(p))
            self.file_list.addItem(item)
            existing.add(str(p))
        if self.file_list.count() and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select images", "", IMAGE_FILTER)
        if paths:
            self._add_paths(paths)

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            self._results.pop(item.data(Qt.UserRole), None)
            self.file_list.takeItem(self.file_list.row(item))

    def _clear_files(self) -> None:
        self.file_list.clear()
        self._results.clear()
        self.canvas.set_original(None)
        self.canvas.set_result(None)
        self.preview_info.setText("—")

    def _on_selection_changed(self, *_args) -> None:
        item = self.file_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        try:
            with Image.open(path) as im:
                self.canvas.set_original(im.convert("RGB"))
        except Exception:  # noqa: BLE001
            self.canvas.set_original(None)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        res = self._results.get(path)
        show_result = self.radio_result.isChecked()
        if res is not None:
            self.canvas.set_result(res.image)
            self.canvas.set_show_result(show_result)
            self.preview_info.setText(
                f"{res.width}×{res.height} · {res.ms} ms · fg {res.coverage:.0%} · {res.out.name}"
            )
        else:
            self.canvas.set_result(None)
            self.canvas.set_show_result(False)  # no result yet: always show the original
            self.preview_info.setText("not processed yet — showing original")

    # ---------------------------------------------------------- processing
    def _options(self) -> ProcessOptions:
        bg_mode = self.bg_combo.currentData()
        if bg_mode == "image" and not self._bg_image_path:
            raise ValueError("Choose a background image first (mode 'Custom image').")
        return ProcessOptions(
            model=self.model_combo.currentData(),
            res_preset=self.quality_combo.currentData(),
            refine=self.refine_combo.currentData(),
            fill_holes=self.fillholes_check.isChecked(),
            feather_px=self.feather_spin.value(),
            defringe=self.defringe_check.isChecked(),
            bg_mode=bg_mode,
            bg_color=self.color_btn.text(),
            bg_image=self._bg_image_path,
            blur_radius=self.blur_spin.value(),
            shadow=ShadowSpec(
                enabled=self.shadow_check.isChecked(),
                color=self.shadow_color_btn.text(),
                opacity=self.shadow_opacity.value(),
                blur=self.shadow_blur.value(),
                offset_y=self.shadow_offset.value(),
            ),
            out_format=self.format_combo.currentData(),
            suffix=self.suffix_edit.text() or "-nobg",
        )

    def _set_busy(self, busy: bool) -> None:
        for w in (self.process_btn, self.process_all_btn):
            w.setEnabled(not busy)

    def _start(self, only_selected: bool) -> None:
        if self._thread is not None:
            return
        try:
            opts = self._options()
        except ValueError as exc:
            QMessageBox.warning(self, "Incomplete settings", str(exc))
            return

        items = (
            self.file_list.selectedItems()
            if only_selected
            else [self.file_list.item(i) for i in range(self.file_list.count())]
        )
        paths = [it.data(Qt.UserRole) for it in items]
        if not paths:
            QMessageBox.information(self, "No images", "Add images first.")
            return

        model_key = opts.model
        engine = self._engines.get(model_key)
        if engine is None:
            engine = MattingEngine(model=model_key)
            self._engines[model_key] = engine

        out_dir = self.outdir_edit.text().strip() or None

        self._set_busy(True)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)

        thread = QThread(self)
        worker = PipelineWorker(engine, opts, paths, out_dir)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.item_done.connect(self._on_item_done)
        worker.item_failed.connect(self._on_item_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._on_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_progress(self, index: int, total: int, message: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(index)
        self.status_label.setText(message)

    def _on_item_done(self, result: ProcessResult) -> None:
        self._results[str(result.src)] = result
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == str(result.src):
                base = Path(result.src)
                item.setText(f"✓ {base.name}\n  {result.width}×{result.height} · {result.ms} ms")
                if self.file_list.currentItem() is item:
                    self._refresh_preview()
                break
        self.status_label.setText(f"✓ {result.out.name} ({result.ms} ms)")

    def _on_item_failed(self, path: str, message: str) -> None:
        self.status_label.setText(f"✗ {Path(path).name}: {message}")

    def _on_finished(self) -> None:
        self.progress.setValue(self.progress.maximum())
        self.status_label.setText(f"Done — {len(self._results)} image(s) processed.")
        self._set_busy(False)
        self._thread = None
        self._worker = None

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("deepvertex-cutout-studio")
    icon_path = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
