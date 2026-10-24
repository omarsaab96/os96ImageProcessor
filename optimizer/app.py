import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QElapsedTimer, QRect, QRectF, QSize, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QAction, QColor, QPalette, QShortcut, QKeySequence, QImage, QPixmap, QIcon, QPainter, QPainterPath, QLinearGradient, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox, QSplitter, QScrollArea, QTabWidget,
    QSizePolicy, QLayout, QGraphicsOpacityEffect, QDialog,
)
from .engine import Settings, Control, discover, run_batch, process, estimate_output, target_size, EXTENSIONS, open_photo
from PIL import Image, ImageOps
from .workflow import WorkflowMixin
from . import __version__

RESIZE_HELP = {
    'Keep original': 'Keeps each image’s original pixel dimensions. Optimization settings still apply.',
    'By dimensions': 'Resizes images to the pixel dimensions below using the selected option.',
    'By resolution': 'Resamples to the exact print width and height at the selected DPI. Pixels = inches × DPI (centimeters ÷ 2.54 × DPI). This may change proportions or enlarge images. Higher DPI cannot recover missing detail.',
}
DIMENSION_HELP = {
    'Exact': 'Sets every image to the specified width and height. Proportions may change, causing stretching. Smaller images are enlarged.',
    'Height': 'Sets every image to the specified height and calculates its width to preserve proportions. Smaller images are enlarged.',
    'Width': 'Sets every image to the specified width and calculates its height to preserve proportions. Smaller images are enlarged.',
    'Auto': 'Landscape and square images use the specified width; portrait images use the specified height. The other dimension is calculated to preserve proportions. Smaller images are enlarged.',
}


class IosSwitch(QCheckBox):
    """Accessible checkbox behavior with a full-row iOS-style switch."""
    def __init__(self, text):
        super().__init__(text)
        self.position = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self.move_thumb)
        self.toggled.connect(self.animate)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 78, 38)

    def hitButton(self, point):
        return self.rect().contains(point)

    def animate(self, checked):
        self.animation.stop()
        self.animation.setStartValue(self.position)
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def move_thumb(self, value):
        self.position = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.5)
        track = QRectF(self.width() - 49, (self.height() - 27) / 2, 48, 27)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#34c759' if self.isChecked() else '#dce1e8'))
        painter.drawRoundedRect(track, 13.5, 13.5)
        painter.setBrush(QColor(0, 0, 0, 22))
        painter.drawEllipse(QRectF(track.left() + 2 + 21 * self.position, track.top() + 3, 23, 23))
        painter.setBrush(QColor('white'))
        painter.drawEllipse(QRectF(track.left() + 2 + 21 * self.position, track.top() + 2, 23, 23))
        painter.setPen(QColor('#243954'))
        font = self.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, self.width() - 64, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self.text())
        # if self.hasFocus():
        #     painter.setPen(QColor('#ff0000'))
        #     painter.setBrush(Qt.NoBrush)
            # painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 15, 15)


class StatusProgressBar(QProgressBar):
    """A full-width progress surface with a continuously moving soft sheen."""
    range_updated = Signal()

    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.animating = False
        self.setMinimumHeight(58)
        self.setTextVisible(False)

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self.range_updated.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        outline = QPainterPath()
        outline.addRoundedRect(bounds, 13, 13)
        painter.setClipPath(outline)
        painter.fillRect(bounds, QColor('#edf3fc'))
        if self.maximum() > self.minimum():
            fraction = max(0, (self.value() - self.minimum()) / (self.maximum() - self.minimum()))
            painter.fillRect(QRectF(0, 0, self.width() * fraction, self.height()), QColor('#c9dfff'))
        if self.animating:
            center = (self.phase * 1.8 - .4) * self.width()
            sheen = QLinearGradient(center - self.width() * .3, 0, center + self.width() * .3, self.height() * .25)
            sheen.setColorAt(0, QColor(150, 199, 255, 0))
            sheen.setColorAt(.35, QColor(174, 211, 255, 100))
            sheen.setColorAt(.5, QColor(255, 255, 255, 205))
            sheen.setColorAt(.65, QColor(174, 211, 255, 100))
            sheen.setColorAt(1, QColor(150, 199, 255, 0))
            painter.fillRect(bounds, sheen)
        gloss = QLinearGradient(0, 0, 0, self.height())
        gloss.setColorAt(0, QColor(255, 255, 255, 105))
        gloss.setColorAt(.5, QColor(255, 255, 255, 0))
        painter.fillRect(bounds, gloss)
        painter.setClipping(False)
        painter.setPen(QColor('#cbd9ee'))
        painter.drawPath(outline)


class HelpLabel(QLabel):
    """Keep the entire wrapped paragraph visible as a settings tab narrows."""
    def __init__(self, text=''):
        super().__init__(text)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def fit_height(self):
        # QLabel.heightForWidth includes its minimum height, so using it here
        # retains the old paragraph's height after shorter text is selected.
        width = max(1, self.contentsRect().width() - 2 * self.margin())
        bounds = self.fontMetrics().boundingRect(
            QRect(0, 0, width, 16777215), Qt.TextWordWrap | Qt.TextExpandTabs, self.text())
        height = max(self.fontMetrics().height(), bounds.height()) + 2 * self.margin()
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def setText(self, text):
        super().setText(text)
        self.fit_height()


def dropped_paths(mime):
    """Accept local supported images and directories, never remote URLs."""
    if not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.is_dir() or (path.is_file() and path.suffix.lower() in EXTENSIONS):
                paths.append(path)
    return paths


class ImageTable(QTableWidget):
    files_dropped = Signal(object)

    def __init__(self):
        super().__init__(0, 4)
        self.drop_enabled = True
        self.drag_active = False
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DropOnly)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.update_empty_style()

    def update_empty_style(self):
        self.setStyleSheet('QTableWidget { background: transparent; border: none; }'
                          if not self.rowCount() else '')
        self.viewport().setAutoFillBackground(bool(self.rowCount()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.viewport().rect()).adjusted(1,1,-1,-1)
        painter.setBrush(QColor('#edf4ff' if self.drag_active else '#f8faff'))
        painter.setPen(QPen(QColor('#2563eb' if self.drag_active else '#acbdd6'), 1.5, Qt.DashLine))
        painter.drawRoundedRect(bounds, 16, 16)
        center = bounds.center().y()
        font = self.font()
        font.setPointSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor('#243954'))
        painter.drawText(QRectF(bounds.left(), center - 38, bounds.width(), 35), Qt.AlignCenter,
                         'Drop images or folders here')
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor('#61738f'))
        painter.drawText(QRectF(bounds.left(), center + 3, bounds.width(), 30), Qt.AlignCenter,
                         'Or use Add images / Add folder to choose files')

    def dragEnterEvent(self, event):
        self.drag_active = bool(self.drop_enabled and dropped_paths(event.mimeData()))
        self.viewport().update()
        if self.drop_enabled and dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.drag_active = False
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        self.drag_active = False
        self.viewport().update()
        paths = dropped_paths(event.mimeData()) if self.drop_enabled else []
        if paths:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.files_dropped.emit(paths)
        else:
            event.ignore()


def file_size(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:,.0f} {unit}' if unit == 'B' else f'{value:,.1f} {unit}'
        value /= 1024


def output_size(value, original, estimated=False):
    label = ('≈ ' if estimated else '') + file_size(value)
    if original:
        label += f' ({(value / original - 1) * 100:+.1f}%)'
    return label


def image_info(path):
    """Read metadata and prepare a small thumbnail in the scanning worker."""
    with open_photo(path) as image:
        size = image.size
        oriented = size[::-1] if image.getexif().get(274) in (5, 6, 7, 8) else size
        details = dict(bytes=path.stat().st_size, size=size, oriented=oriented,
                       frames=getattr(image, 'n_frames', 1))
        try:
            image.thumbnail((40, 40))
            preview = ImageOps.exif_transpose(image).convert('RGBA')
            details['thumbnail'] = QImage(preview.tobytes(), preview.width, preview.height,
                                          QImage.Format_RGBA8888).copy()
        except Exception:
            # A failed preview must not hide otherwise readable metadata.
            pass
        return details


class Estimator(QThread):
    result = Signal(int, int, object, str)

    def __init__(self, jobs, settings, generation):
        super().__init__()
        self.jobs, self.settings, self.generation = jobs, settings, generation
        self.control = Control()

    def run(self):
        # A single low-priority worker bounds RAM and never writes to source files.
        with tempfile.TemporaryDirectory(prefix='os96-preview-') as directory:
            settings = replace(self.settings, output=Path(directory), in_place=False,
                               overwrite=True, workers=1)
            for index, job in enumerate(self.jobs):
                if self.control.stopped:
                    break
                quick = settings.smart or settings.web
                if quick:
                    try:
                        after = estimate_output(job, settings, self.control, settings.output / 'sample')
                    except Exception:
                        after = None
                    result = 'done' if after is not None else 'error'
                else:
                    result, _, after = process(job, settings, self.control, lambda _: None)
                if result == 'cancelled' or self.control.stopped:
                    break
                self.result.emit(self.generation, index, after if result == 'done' else None,
                                 '' if result == 'done' else 'Unable to estimate; check the image during processing.')
                (settings.output / job.relative).unlink(missing_ok=True)


class Scanner(QThread):
    result = Signal(object, object, object)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        try:
            jobs, errors = discover(self.paths)
            info = []
            for job in jobs:
                try:
                    info.append(image_info(job.source))
                except Exception as exc:
                    info.append({'error': str(exc)})
            self.result.emit(jobs, errors, info)
        except Exception as exc:
            self.result.emit([], [str(exc)], [])


class Worker(QThread):
    status = Signal(int, str)
    progress = Signal(int, object)
    result = Signal(object)

    def __init__(self, jobs, settings):
        super().__init__()
        self.jobs, self.settings, self.control = jobs, settings, Control()

    def run(self):
        try:
            self.result.emit(run_batch(self.jobs, self.settings, self.control,
                                       self.status.emit, self.progress.emit))
        except Exception as exc:
            self.result.emit({'fatal': str(exc)})


class Window(WorkflowMixin, QMainWindow):
    def __init__(self, persist=False, preferences=None):
        super().__init__()
        self.setWindowTitle(f'OS96 Image Optimizer {__version__}')
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent.parent / 'assets' / 'app.ico')))
        self.file_menu = self.menuBar().addMenu('File')
        file_menu = self.file_menu
        self.add_files_action = file_menu.addAction('Add images…')
        self.add_files_action.triggered.connect(self.select_files)
        self.add_folder_action = file_menu.addAction('Add folder…')
        self.add_folder_action.triggered.connect(self.select_folder)
        if sys.platform == 'darwin':
            # Native macOS menus need the action inside a menu before merging.
            self.settings_action = QAction('Settings…', self)
            self.settings_action.setMenuRole(QAction.PreferencesRole)
            self.settings_action.setShortcut(QKeySequence(QKeySequence.Preferences))
            file_menu.addAction(self.settings_action)
        else:
            self.settings_action = self.menuBar().addAction('Settings')
        self.settings_action.triggered.connect(self.show_settings)
        about = self.menuBar().addMenu('Help').addAction('About OS96')
        about.triggered.connect(lambda: QMessageBox.about(self, 'About OS96',
            f'OS96 Image Optimizer {__version__}\nLocal batch optimization and resizing.\n'
            'JPEG, PNG, WebP, TIFF, BMP\nThird-party license notices are included beside the application.'))
        self.resize(1160, 700)
        self.jobs, self.paths, self.worker, self.scanner = [], [], None, None
        self.excluded = set()
        self.setAcceptDrops(True)
        self.info, self.estimator = [], None
        self.generation, self.busy, self.closing = 0, False, False
        self.estimate_timer = QTimer(self)
        self.estimate_timer.setSingleShot(True)
        self.estimate_timer.setInterval(500)
        self.estimate_timer.timeout.connect(self.launch_estimates)
        main = QWidget()
        self.setCentralWidget(main)
        layout = QVBoxLayout(main)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel('Image Optimizer')
        title.setObjectName('title')
        layout.addWidget(title)
        layout.addWidget(QLabel('A lighter library. Your folders, filenames, and workflow preserved.'))
        split = QSplitter()
        layout.addWidget(split, 1)
        left, right = QWidget(), QWidget()
        right.setMinimumWidth(390)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([610, 390])
        ll, rr = QVBoxLayout(left), QVBoxLayout(right)
        ll.setContentsMargins(0, 18, 12, 0)
        rr.setContentsMargins(12, 18, 0, 0)
        self.options_tabs = QTabWidget()
        rr.addWidget(self.options_tabs)
        row = QHBoxLayout()
        self.add_files = QPushButton('+ Add images')
        self.add_folder = QPushButton('+ Add folder')
        self.remove = QPushButton('Remove selected')
        self.remove.setToolTip('Remove selected rows from the queue; source files are kept. Delete / Backspace also work.')
        self.clear = QPushButton('Clear')
        for button in (self.add_files, self.add_folder, self.remove, self.clear):
            row.addWidget(button)
        ll.addLayout(row)
        self.count = QLabel()
        self.count.hide()
        ll.addWidget(self.count)
        self.table = ImageTable()
        self.table.setIconSize(QSize(40, 40))
        self.table.files_dropped.connect(self.scan)
        self.table.itemSelectionChanged.connect(self.update_remove)
        for key in ('Delete', 'Backspace'):
            shortcut = QShortcut(QKeySequence(key), self.table)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.remove_selected)
        self.table.setHorizontalHeaderLabels(['File name', 'Status', 'Original', 'Est. output'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 150)
        for column in range(2, 4):
            self.table.setColumnWidth(column, 165)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setMinimumSectionSize(110)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        ll.addWidget(self.table)
        self.estimate_note = QLabel('Output sizes are estimated by a background trial encode. Originals are never modified.')
        self.estimate_note.setWordWrap(True)
        ll.addWidget(self.estimate_note)
        self.resize_enabled = IosSwitch('Enable resizing')
        self.compression_enabled = IosSwitch('Enable compression')
        self.compression_enabled.setChecked(True)
        self.resize_box = QWidget()
        form = QFormLayout(self.resize_box)
        self.mode = QComboBox()
        self.mode.addItems(['By dimensions', 'By resolution'])
        self.dimension_mode = QComboBox()
        self.dimension_mode.addItems(list(DIMENSION_HELP))
        for combo, explanations in ((self.mode, RESIZE_HELP), (self.dimension_mode, DIMENSION_HELP)):
            for index in range(combo.count()):
                combo.setItemData(index, explanations[combo.itemText(index)], Qt.ToolTipRole)
        self.width, self.height = QSpinBox(), QSpinBox()
        for spin, value in [(self.width, 1920), (self.height, 1080)]:
            spin.setRange(1, 100000)
            spin.setValue(value)
        self.dpi = QSpinBox()
        self.dpi.setRange(1, 2400)
        self.dpi.setValue(300)
        self.print_width, self.print_height = QDoubleSpinBox(), QDoubleSpinBox()
        for spin, value in ((self.print_width, 6), (self.print_height, 4)):
            spin.setRange(.01, 200)
            spin.setDecimals(2)
            spin.setValue(value)
        self.print_unit = QComboBox()
        self.print_unit.addItems(['in', 'cm'])
        form.addRow('Mode', self.mode)
        form.addRow('Option', self.dimension_mode)
        form.addRow('Width (px)', self.width)
        form.addRow('Height (px)', self.height)
        form.addRow('Resolution (DPI)', self.dpi)
        form.addRow('Print units', self.print_unit)
        form.addRow('Print width', self.print_width)
        form.addRow('Print height', self.print_height)
        self.resize_note = HelpLabel()
        form.addRow(self.resize_note)
        self.add_options_tab(self.resize_box, 'Resize', self.resize_enabled)
        self.compression_box = QWidget()
        form = QFormLayout(self.compression_box)
        self.compression = QComboBox()
        self.compression.addItems(['Automatic', 'Lossless', 'Manual quality'])
        self.compression.setToolTip('Choose one compression strategy. Save for web controls metadata and color handling separately.')
        self.web = QCheckBox('Save for web')
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(85)
        self.png = QSpinBox()
        self.png.setRange(0, 9)
        self.png.setValue(6)
        self.metadata = QCheckBox('Keep metadata')
        self.metadata.setChecked(True)
        self.color_profile = QCheckBox('Keep color profile')
        self.color_profile.setChecked(True)
        self.threads = QSpinBox()
        self.threads.setRange(0, 8)
        self.threads.setSpecialValueText('Auto')
        self.threads.setValue(0)
        def help_text(text):
            label = HelpLabel(text)
            label.setStyleSheet('color: #58697f; font-size: 11px;')
            form.addRow(label)
            return label
        form.addRow('Compression', self.compression)
        self.lossless_help = help_text('')
        form.addRow('JPEG / WebP quality', self.quality)
        self.quality_help = help_text('1–100: higher values preserve more detail and usually create larger files. Applies only to JPEG and lossy WebP; 100 is still not mathematically lossless.')
        form.addRow('PNG compression', self.png)
        self.png_help = help_text('0–9: higher levels spend more time compressing PNG files. Pixel quality is unchanged at every level.')
        self.add_options_tab(self.compression_box, 'Compression', self.compression_enabled)
        self.settings_box = QWidget()
        form = QFormLayout(self.settings_box)
        form.addRow(self.web)
        self.web_help = help_text('')
        form.addRow(self.metadata)
        self.metadata_opacity = QGraphicsOpacityEffect(self.metadata)
        self.metadata.setGraphicsEffect(self.metadata_opacity)
        help_text('Keeps supported camera information, descriptions, and other metadata. Turn off to remove it. Required orientation and explicitly selected print density are retained.')
        form.addRow(self.color_profile)
        self.profile_opacity = QGraphicsOpacityEffect(self.color_profile)
        self.color_profile.setGraphicsEffect(self.profile_opacity)
        help_text('Keeps embedded ICC color profiles independently of metadata. Recommended: removing a profile may change how colors appear.')
        self.only_smaller = QCheckBox('Only save files smaller than the original')
        self.only_smaller.setToolTip('When enabled, larger results are skipped, including resized and print outputs.')
        form.addRow(self.only_smaller)
        form.addRow('Parallel images', self.threads)
        help_text('Auto manages memory and runs large photos one at a time. Select 1–8 for an explicit number of simultaneous images. Eight large photos can use several gigabytes of memory; more parallelism may be slower if memory is limited.')
        note = HelpLabel('Animated / multipage images are skipped. Metadata and color-profile support vary by format.')
        form.addRow(note)
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Settings')
        self.settings_dialog.resize(560, 660)
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.NoFrame)
        self.settings_box.layout().setAlignment(Qt.AlignTop)
        self.settings_box.layout().setFormAlignment(Qt.AlignTop)
        self.settings_box.layout().setSizeConstraint(QLayout.SetMinimumSize)
        settings_scroll.setWidget(self.settings_box)
        settings_layout.addWidget(settings_scroll)
        settings_buttons = QHBoxLayout()
        settings_buttons.addStretch()
        settings_done = QPushButton('Done')
        settings_done.setObjectName('primary')
        settings_done.clicked.connect(self.settings_dialog.accept)
        settings_buttons.addWidget(settings_done)
        settings_layout.addLayout(settings_buttons)
        self.output_box = QWidget()
        form = QVBoxLayout(self.output_box)
        self.in_place = QCheckBox('Replace originals in place')
        form.addWidget(self.in_place)
        self.output = QLineEdit()
        self.output.setPlaceholderText('Choose output folder…')
        self.browse = QPushButton('Choose folder')
        form.addWidget(self.output)
        form.addWidget(self.browse)
        self.overwrite = QCheckBox('Overwrite existing files in output folder')
        form.addWidget(self.overwrite)
        self.destination_opacity = {}
        for control in (self.output, self.browse, self.overwrite):
            effect = QGraphicsOpacityEffect(control)
            control.setGraphicsEffect(effect)
            self.destination_opacity[control] = effect
        self.only_smaller.toggled.connect(self.schedule_estimates)
        self.add_options_tab(self.output_box, 'Destination')
        self.resize_enabled.toggled.connect(self.update_options)
        self.compression_enabled.toggled.connect(self.update_options)
        self.progress = StatusProgressBar()
        self.progress.setValue(0)
        footer = QHBoxLayout(self.progress)
        footer.setContentsMargins(16, 6, 12, 6)
        footer.setSpacing(12)
        messages = QVBoxLayout()
        messages.setSpacing(2)
        self.summary = QLabel('Ready')
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet('font-weight: 600; color: #17283f;')
        messages.addWidget(self.summary)
        details = QHBoxLayout()
        details.setSpacing(14)
        self.strategy_label = QLabel('Compression: Automatic')
        self.strategy_label.setStyleSheet('color: #536b8b; font-size: 11px;')
        details.addWidget(self.strategy_label)
        self.activity = QLabel()
        self.activity.setStyleSheet('color: #536b8b; font-size: 11px;')
        details.addWidget(self.activity)
        self.elapsed_label = QLabel()
        self.elapsed_label.setStyleSheet('color: #536b8b; font-size: 11px;')
        details.addWidget(self.elapsed_label)
        self.batch_clock = QElapsedTimer()
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(250)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        details.addStretch()
        messages.addLayout(details)
        footer.addLayout(messages, 1)
        self.percentage = QLabel('0%')
        self.percentage.setMinimumWidth(46)
        self.percentage.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.percentage.setStyleSheet('font-size: 18px; font-weight: 600; color: #305b98;')
        footer.addWidget(self.percentage)
        self.progress.valueChanged.connect(self.update_percentage)
        self.progress.range_updated.connect(self.update_percentage)
        self.pause = QPushButton('Pause')
        self.stop = QPushButton('Stop')
        self.start = QPushButton('Start optimization')
        self.start.setObjectName('primary')
        for button in (self.pause, self.stop, self.start):
            button.setMinimumHeight(26)
            footer.addWidget(button)
        self.pause.hide()
        self.stop.hide()
        layout.addWidget(self.progress)
        self.loading_frame = 0
        self.loading_text = ''
        self.loading_timer = QTimer(self)
        self.loading_timer.setInterval(16)
        self.loading_timer.timeout.connect(self.animate_loading)
        self.pause.setEnabled(False)
        self.stop.setEnabled(False)
        self.add_files.clicked.connect(self.select_files)
        self.add_folder.clicked.connect(self.select_folder)
        self.clear.clicked.connect(self.clear_jobs)
        self.remove.clicked.connect(self.remove_selected)
        self.browse.clicked.connect(self.select_output)
        self.start.clicked.connect(self.start_batch)
        self.pause.clicked.connect(self.toggle_pause)
        self.stop.clicked.connect(self.stop_batch)
        self.mode.currentTextChanged.connect(self.update_options)
        self.compression.currentTextChanged.connect(self.update_options)
        self.web.toggled.connect(self.update_options)
        self.in_place.toggled.connect(self.update_options)
        for widget in (self.width, self.height, self.dpi, self.print_width, self.print_height, self.quality, self.png):
            widget.valueChanged.connect(self.schedule_estimates)
        self.dimension_mode.currentTextChanged.connect(self.update_options)
        self.print_unit.currentTextChanged.connect(self.schedule_estimates)
        self.metadata.toggled.connect(self.schedule_estimates)
        self.color_profile.toggled.connect(self.schedule_estimates)
        self.update_options()
        self.update_remove()
        self.setup_workflow(persist, ll, rr, preferences)

    def add_options_tab(self, options, title, switch=None):
        options.layout().setContentsMargins(0, 0, 0, 0)
        options.layout().setAlignment(Qt.AlignTop)
        if isinstance(options.layout(), QFormLayout):
            options.layout().setFormAlignment(Qt.AlignTop)
            options.layout().setVerticalSpacing(8)
        options.layout().setSizeConstraint(QLayout.SetMinimumSize)
        options.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        page = QWidget()
        palette = page.palette()
        palette.setColor(QPalette.Window, QColor('white'))
        page.setPalette(palette)
        page.setAutoFillBackground(True)
        layout = QVBoxLayout(page)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        layout.setContentsMargins(10, 10, 10, 10)
        if switch is not None:
            layout.addWidget(switch)
            layout.setSpacing(12)
            opacity = QGraphicsOpacityEffect(options)
            opacity.setOpacity(1.0 if switch.isChecked() else .4)
            options.setGraphicsEffect(opacity)
            switch.toggled.connect(lambda checked: opacity.setOpacity(1.0 if checked else .4))
        layout.addWidget(options)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(page)
        self.options_tabs.addTab(scroll, title)

    def dragEnterEvent(self, event):
        if not self.busy and dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = dropped_paths(event.mimeData()) if not self.busy else []
        if paths:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.scan(paths)
        else:
            event.ignore()

    def update_remove(self):
        self.remove.setEnabled(not self.busy and bool(self.table.selectionModel().selectedRows()))

    def remove_selected(self):
        if self.busy:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            return
        # Invalidate queued preview results before changing row indices.
        self.generation += 1
        if self.estimator and self.estimator.isRunning():
            self.estimator.control.stop()
        for row in rows:
            self.excluded.add(self.jobs[row].source.resolve())
            del self.jobs[row]
            del self.info[row]
            self.table.removeRow(row)
        self.table.clearSelection()
        self.update_count()
        self.update_remove()
        self.schedule_estimates()
        self.summary.setText(f'Removed {len(rows):,} from queue · Source files kept')

    def update_count(self):
        self.count.setVisible(bool(self.jobs))
        self.table.update_empty_style()
        self.table.horizontalHeader().setVisible(bool(self.jobs))
        self.table.verticalHeader().setVisible(bool(self.jobs))
        self.table.viewport().update()
        self.count.setText(f'{len(self.jobs):,} images · Drop images or folders to add more'
                           if self.jobs else '')

    def update_options(self, *_):
        self.resize_box.setEnabled(self.resize_enabled.isChecked() and not self.busy)
        self.compression_box.setEnabled(self.compression_enabled.isChecked() and not self.busy)
        strategy = ('Compression: ' + self.compression.currentText()) if self.compression_enabled.isChecked() else 'Compression off'
        self.strategy_label.setText(strategy + (' | Resize on' if self.resize_enabled.isChecked() else ''))
        mode = self.mode.currentText()
        form = self.resize_box.layout()
        dimensions = mode == 'By dimensions'
        option = self.dimension_mode.currentText()
        form.setRowVisible(self.dimension_mode, dimensions)
        form.setRowVisible(self.width, dimensions and option in ('Exact', 'Width', 'Auto'))
        form.setRowVisible(self.height, dimensions and option in ('Exact', 'Height', 'Auto'))
        for field in (self.dpi, self.print_unit, self.print_width, self.print_height):
            form.setRowVisible(field, mode == 'By resolution')
        self.resize_note.setText(DIMENSION_HELP[option] if dimensions else RESIZE_HELP[mode])
        web = self.web.isChecked()
        self.web_help.setVisible(True)
        self.metadata.setEnabled(not web)
        self.color_profile.setEnabled(not web)
        self.metadata_opacity.setOpacity(.4 if web else 1.0)
        self.profile_opacity.setOpacity(.4 if web else 1.0)
        smart = self.compression.currentText() == 'Automatic'
        manual = self.compression.currentText() == 'Manual quality'
        self.png.setEnabled(not smart)
        self.compression_box.layout().setRowVisible(self.png, not smart)
        self.compression_box.layout().setRowVisible(self.png_help, not smart)
        self.compression_box.layout().setRowVisible(self.quality, manual)
        self.compression_box.layout().setRowVisible(self.quality_help, manual)
        if smart:
            self.lossless_help.setText('Balances smaller files with image quality automatically. JPEGs may lose a little fine detail; PNG and WebP remain lossless. Keeps original dimensions unless resizing is selected. Uses the smaller original when recompression would enlarge an unchanged image. CMYK JPEG uses maximum quality. Estimates use small previews.')
        elif self.compression.currentText() == 'Lossless':
            self.lossless_help.setText('PNG and WebP encode losslessly after resizing. JPEGs preserve compressed pixels when keeping original dimensions with Save for web off. Resizing or web color conversion requires JPEG encoding at quality 100, which can still change pixels. Making an image smaller removes fine detail. Use PNG or lossless WebP when exact resized pixels are required.')
        else:
            self.lossless_help.setText('Set JPEG / WebP quality below to control the size/detail tradeoff. PNG, TIFF, and BMP do not use this quality setting.')
        for widget in (self.output, self.browse, self.overwrite):
            widget.setEnabled(not self.in_place.isChecked())
            self.destination_opacity[widget].setOpacity(.4 if self.in_place.isChecked() else 1.0)
        self.schedule_estimates()

    def preview_settings(self):
        return Settings(output=Path('.'), resize=self.mode.currentText() if self.resize_enabled.isChecked() else 'Keep original',
                        compress=self.compression_enabled.isChecked(),
                        width=self.width.value(), height=self.height.value(),
                        dimension_mode=self.dimension_mode.currentText(),
                        dpi=self.dpi.value(), print_width=self.print_width.value(),
                        print_height=self.print_height.value(), print_unit=self.print_unit.currentText(),
                        lossless=not self.compression_enabled.isChecked() or self.compression.currentText() != 'Manual quality',
                        smart=self.compression_enabled.isChecked() and self.compression.currentText() == 'Automatic',
                        web=self.web.isChecked(),
                        only_smaller=self.only_smaller.isChecked(),
                        quality=self.quality.value(), png_level=self.png.value(), metadata=self.metadata.isChecked(),
                        color_profile=self.color_profile.isChecked())

    def schedule_estimates(self, *_):
        self.generation += 1
        self.estimate_timer.stop()
        if self.estimator and self.estimator.isRunning():
            self.estimator.control.stop()
        if self.busy:
            return
        if not self.resize_enabled.isChecked() and not self.compression_enabled.isChecked():
            self.set_loading('')
            self.estimate_note.setText('Enable Resize or Compression to estimate and process images.')
            for index in range(len(self.jobs)):
                self.table.item(index, 3).setText('No steps enabled')
            return
        settings = self.preview_settings()
        quick = settings.smart or settings.web
        self.estimate_note.setText(
            'Sizes are rough small preview estimates. Full compression runs on Start; larger results are allowed unless Only save smaller is enabled.'
            if quick else 'Output sizes are estimated by a background trial encode. Originals are never modified.')
        for index, info in enumerate(self.info):
            valid = 'error' not in info and info['frames'] == 1
            if valid:
                size = target_size(info['oriented'], settings)
                dimensions = f'{size[0]:,} × {size[1]:,} px'
            else:
                dimensions = ''
            item = self.table.item(index, 3)
            item.setData(Qt.UserRole, dimensions)
            item.setText(f'{dimensions}\n≈ …' if valid else 'Unavailable')
            item.setToolTip('Estimating from a small preview; actual output may differ.' if quick else '')
        if self.jobs:
            self.set_loading('Estimating')
            self.estimate_timer.start()
        else:
            self.set_loading('')

    def launch_estimates(self):
        if self.busy or not self.jobs:
            return
        if self.estimator and self.estimator.isRunning():
            self.estimate_timer.start()
            return
        self.estimator = Estimator(self.jobs.copy(), self.preview_settings(), self.generation)
        self.estimator.result.connect(self.estimated)
        self.estimator.finished.connect(self.estimates_finished)
        self.estimator.start(QThread.LowPriority)

    def estimated(self, generation, index, size, error):
        if generation != self.generation or self.busy:
            return
        item = self.table.item(index, 3)
        dimensions = item.data(Qt.UserRole)
        label = output_size(size, self.info[index].get('bytes'), estimated=True) if size is not None else 'Unavailable'
        item.setText(f'{dimensions}\n{label}' if dimensions else label)
        item.setToolTip(error or ('Rough small preview estimate; actual output may differ. The size policy is applied when saving.'
                                 if self.compression.currentText() == 'Automatic' or self.web.isChecked() else
                                 'Trial encode using current settings; actual output may vary if the source changes.'))

    def estimates_finished(self):
        if not self.busy and not self.estimate_timer.isActive():
            self.set_loading('')
        if self.closing:
            self.close()

    def set_loading(self, text):
        self.loading_text = text
        self.progress.animating = bool(text)
        self.progress.update()
        if text:
            self.animate_loading()
            self.loading_timer.start()
        else:
            self.loading_timer.stop()
            self.activity.clear()

    def animate_loading(self):
        self.activity.setText(f'{self.loading_text}…')
        self.progress.phase = (self.progress.phase + .008) % 1.0
        self.progress.update()
        self.loading_frame += 1

    def update_percentage(self, *_):
        span = self.progress.maximum() - self.progress.minimum()
        self.percentage.setText(f'{max(0, round((self.progress.value() - self.progress.minimum()) / span * 100))}%' if span else '…')

    def update_elapsed(self):
        if self.batch_clock.isValid():
            seconds = self.batch_clock.elapsed() // 1000
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            duration = f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes:02}:{seconds:02}'
            self.elapsed_label.setText(f'Elapsed {duration}')

    def batch_finished(self):
        if self.elapsed_timer.isActive():
            self.update_elapsed()
            self.elapsed_timer.stop()
        self.set_busy(False, refresh=False)

    def show_running_controls(self, running):
        self.start.setVisible(not running)
        self.pause.setVisible(running)
        self.stop.setVisible(running)

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Select images', '', 'Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp)')
        self.scan(paths)

    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Select input folder')
        if path:
            self.scan([path])

    def show_settings(self):
        self.settings_dialog.exec()
        self.save_preferences()

    def select_output(self):
        path = QFileDialog.getExistingDirectory(self, 'Select output folder')
        if path:
            self.output.setText(path)

    def scan(self, paths):
        if self.busy or not paths:
            return
        paths = [Path(p).resolve() for p in paths]
        # Explicitly adding an image/folder again restores its excluded entries.
        self.excluded = {p for p in self.excluded if not any(
            p == root or (root.is_dir() and root in p.parents) for root in paths)}
        self.paths.extend(p for p in paths if p not in self.paths)
        self.set_busy(True)
        self.pause.setEnabled(False)
        self.stop.setEnabled(False)
        self.summary.setText('Scanning folders…')
        self.scanner = Scanner(self.paths.copy())
        self.scanner.result.connect(self.scanned)
        self.scanner.finished.connect(lambda: self.set_busy(False))
        self.scanner.start()

    def scanned(self, jobs, errors, info=None):
        entries = [(job, details) for job, details in zip(jobs, info or [])
                   if job.source.resolve() not in self.excluded]
        self.jobs = [job for job, _ in entries]
        self.info = [details for _, details in entries]
        jobs = self.jobs
        self.table.setRowCount(len(jobs))
        for index, job in enumerate(jobs):
            item = QTableWidgetItem(str(job.relative))
            item.setToolTip(str(job.source))
            self.table.setItem(index, 0, item)
            self.table.setItem(index, 1, QTableWidgetItem('Ready'))
            for column in range(2, 4):
                self.table.setItem(index, column, QTableWidgetItem('Unavailable'))
            details = self.info[index]
            if 'thumbnail' in details:
                item.setIcon(QIcon(QPixmap.fromImage(details['thumbnail'])))
            if 'error' not in details:
                w, h = details['size']
                self.table.item(index, 2).setText(f"{w:,} × {h:,} px\n{file_size(details['bytes'])}")
                self.table.item(index, 2).setToolTip('Original file size and stored pixel dimensions; output dimensions account for EXIF orientation.')
            else:
                self.table.item(index, 2).setToolTip(details['error'])
        self.update_count()
        self.update_remove()
        self.summary.setText('Ready')
        if errors:
            QMessageBox.warning(self, 'Scan issues', '\n'.join(errors))

    def clear_jobs(self):
        if self.busy:
            return
        self.paths.clear()
        self.excluded.clear()
        self.scanned([], [])
        self.schedule_estimates()

    def set_busy(self, busy, refresh=True):
        self.busy = busy
        if not busy:
            self.show_running_controls(False)
        self.set_loading('Processing' if busy else '')
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.table.drop_enabled = not busy
        self.update_remove()
        if busy:
            self.estimate_timer.stop()
            self.generation += 1
            if self.estimator and self.estimator.isRunning():
                self.estimator.control.stop()
        for widget in (self.add_files, self.add_folder, self.clear, self.resize_box,
                       self.compression_box, self.settings_box, self.output_box, self.start, *getattr(self, 'workflow_controls', [])):
            widget.setEnabled(not busy)
        self.settings_action.setEnabled(not busy)
        self.add_files_action.setEnabled(not busy)
        self.add_folder_action.setEnabled(not busy)
        self.resize_enabled.setEnabled(not busy)
        self.compression_enabled.setEnabled(not busy)
        self.resize_box.setEnabled(not busy and self.resize_enabled.isChecked())
        self.compression_box.setEnabled(not busy and self.compression_enabled.isChecked())
        self.pause.setEnabled(busy)
        self.stop.setEnabled(busy)
        if not busy and refresh:
            self.schedule_estimates()

    def start_batch(self):
        if not self.resize_enabled.isChecked() and not self.compression_enabled.isChecked():
            QMessageBox.information(self, 'Choose a step', 'Enable Resize or Compression before starting.')
            return
        if not self.jobs:
            QMessageBox.information(self, 'Add images', 'Choose images or a folder first.')
            return
        in_place = self.in_place.isChecked()
        if not in_place and not self.output.text().strip():
            QMessageBox.warning(self, 'Choose destination', 'Choose an output folder first.')
            return
        if in_place or self.overwrite.isChecked():
            if QMessageBox.question(self, 'Confirm replacement', 'Existing images will be replaced. Keep a backup of originals. Continue?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        output = Path(self.output.text()).expanduser().resolve() if not in_place else Path('.')
        settings = replace(self.preview_settings(), output=output, in_place=in_place,
                           workers=self.threads.value(), overwrite=self.overwrite.isChecked())
        # Reject output trees inside input trees: repeated runs must not ingest prior output.
        if not in_place:
            for path in self.paths:
                if path.is_dir() and (output == path.resolve() or path.resolve() in output.parents):
                    QMessageBox.warning(self, 'Output overlaps input', 'Choose a destination outside input folders, or use Replace originals.')
                    return
        self.set_busy(True)
        self.show_running_controls(True)
        self.pause.setText('Pause')
        self.progress.setRange(0, len(self.jobs))
        self.progress.setValue(0)
        self.summary.setText(f'Processing {len(self.jobs):,} image' + ('s' if len(self.jobs) != 1 else ''))
        for i in range(len(self.jobs)):
            self.table.item(i, 1).setText('Queued')
        self.worker = Worker(self.jobs.copy(), settings)
        self.capture_batch(settings)
        self.worker.status.connect(self.image_status)
        self.worker.progress.connect(self.batch_progress)
        self.worker.result.connect(self.completed)
        self.worker.finished.connect(self.batch_finished)
        self.batch_clock.start()
        self.update_elapsed()
        self.elapsed_timer.start()
        self.worker.start()

    def image_status(self, index, message):
        self.table.item(index, 1).setText(message)
        self.table.item(index, 1).setToolTip(message)
        if (message == 'Done' or message == 'Skipped · output exists') and self.worker:
            settings = self.worker.settings
            job = self.jobs[index]
            destination = job.source if settings.in_place else settings.output / job.relative
            try:
                size = destination.stat().st_size
            except OSError:
                return
            item = self.table.item(index, 3)
            dimensions = item.data(Qt.UserRole)
            label = output_size(size, self.info[index].get('bytes'))
            item.setText(f'{dimensions}\n{label}' if dimensions else label)
            item.setToolTip('Existing output file size; image was skipped.' if message.startswith('Skipped')
                            else 'Actual output file size.')
        elif message.startswith(('Error', 'Not processed', 'Cancelled', 'Skipped')):
            item = self.table.item(index, 3)
            dimensions = item.data(Qt.UserRole)
            label = 'Skipped: would be larger' if message == 'Skipped · output would be larger' else 'No output'
            item.setText(f'{dimensions}\n{label}' if dimensions else label)
            item.setToolTip(message)

    def batch_progress(self, count, totals):
        self.progress.setValue(count)
        saved = (totals['before'] - totals['after']) / 1048576
        self.summary.setText(f"{count:,} / {len(self.jobs):,} · {totals['error']} errors · {saved:.2f} MB saved")

    def toggle_pause(self):
        if self.worker:
            paused = not self.worker.control.paused
            self.worker.control.pause(paused)
            self.pause.setText('Continue' if paused else 'Pause')
            self.summary.setText('Pausing at safe checkpoints…' if paused else 'Processing…')
            if paused:
                self.set_loading('')
                self.activity.setText('Paused')
            else:
                self.set_loading('Processing')

    def stop_batch(self):
        if self.worker:
            self.worker.control.stop()
            self.set_loading('Stopping')
            self.pause.setEnabled(False)
            self.stop.setEnabled(False)
            self.summary.setText('Stopping after current encoding operations…')

    def completed(self, totals):
        self.update_elapsed()
        self.elapsed_timer.stop()
        if 'fatal' in totals:
            QMessageBox.critical(self, 'Processing error', totals['fatal'])
            self.summary.setText('Processing failed')
            return
        stopped = self.worker.control.stopped
        for i in range(len(self.jobs)):
            if self.table.item(i, 1).text() == 'Queued':
                self.image_status(i, 'Not processed · stopped')
            elif self.table.item(i, 1).text() == 'Done' or self.table.item(i, 1).text().startswith('Skipped'):
                self.image_status(i, self.table.item(i, 1).text())
        saved = (totals['before'] - totals['after']) / 1048576
        self.summary.setText(f"{'Stopped' if stopped else 'Complete'} · {totals['done']} done · {totals['skipped']} skipped · {totals['error']} errors · {saved:.2f} MB saved")
        self.finish_report(totals)

    def closeEvent(self, event):
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.control.stop()
            self.summary.setText('Stopping preview; close again when it finishes.')
            event.ignore()
            return
        if (self.worker and self.worker.isRunning()) or (self.scanner and self.scanner.isRunning()):
            QMessageBox.information(self, 'Work in progress', 'Stop processing and wait for active operations to finish before closing.')
            event.ignore()
        elif self.estimator and self.estimator.isRunning():
            self.closing = True
            self.estimate_timer.stop()
            self.estimator.control.stop()
            event.ignore()
        else:
            self.save_preferences()
            event.accept()


def create_application():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in {
        QPalette.Window: '#f4f6fa', QPalette.WindowText: '#17283f',
        QPalette.Base: '#ffffff', QPalette.AlternateBase: '#f7f9fc',
        QPalette.Text: '#17283f', QPalette.Button: '#ffffff',
        QPalette.ButtonText: '#17283f', QPalette.Highlight: '#2563eb',
        QPalette.HighlightedText: '#ffffff', QPalette.ToolTipBase: '#ffffff',
        QPalette.ToolTipText: '#17283f',
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    check_icon = (Path(__file__).resolve().parent.parent / 'assets/checkbox-check.svg').as_posix()
    app.setStyleSheet('''
        QWidget { font-family: "Segoe UI", "Helvetica Neue"; font-size: 12px; }
        QMainWindow { background: #f4f6fa; }
        QLabel#title { font-size: 29px; font-weight: 700; color: #17283f; }
        QPushButton { padding: 9px 14px; border-radius: 6px; border: 1px solid #ccd5e1; background: white; }
        QPushButton:hover { background: #e8effa; }
        QPushButton#primary { background: #2563eb; color: white; border: none; font-weight: 600; }
        QPushButton:disabled { color: #939ba7; background: #edf0f5; }
        QCheckBox { spacing: 7px; }
        QCheckBox::indicator { width: 14px; height: 14px; background: #e9eef6; border-radius: 3px; }
        QCheckBox::indicator:hover { border-color: #2563eb; }
        QCheckBox::indicator:checked { border-color: #2563eb; background: #2563eb; image: url("CHECK_ICON"); }
        QCheckBox::indicator:disabled { border-color: #8290a3; background: #f1f4f8; }
        QCheckBox::indicator:checked:disabled { border-color: #8290a3; background: #8290a3; }
        QTableWidget { border: 1px solid #d9e0ea; background: white; alternate-background-color: #f7f9fc; }
        QHeaderView::section { background: #e9eef6; padding: 8px; border: none; }
        QTabWidget::pane { border: 1px solid #d9e0ea; border-radius: 6px; background: white; }
        QTabBar::tab { padding: 9px 12px; background: #e9eef6; color: #345174; border: 1px solid #d9e0ea; }
        QTabBar::tab:selected { background: white; color: #2563eb; font-weight: 600; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 5px; }
        QProgressBar { border: none; border-radius: 5px; background: #e0e7f1; text-align: center; height: 19px; }
        QProgressBar::chunk { background: #5390ed; border-radius: 5px; }
    '''.replace('CHECK_ICON', check_icon))
    return app


def main():
    app = create_application()
    window = Window(persist=True)
    window.show()
    sys.exit(app.exec())
