import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRect
from PySide6.QtGui import QColor, QPalette, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QLineEdit, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox, QSplitter, QScrollArea, QTabWidget,
    QSizePolicy, QLayout,
)
from .engine import Settings, Control, discover, run_batch, process, target_size, EXTENSIONS
from PIL import Image

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
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DropOnly)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)

    def dragEnterEvent(self, event):
        if self.drop_enabled and dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
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


def image_info(path):
    """Read headers without decoding the full image."""
    with Image.open(path) as image:
        size = image.size
        oriented = size[::-1] if image.getexif().get(274) in (5, 6, 7, 8) else size
        return dict(bytes=path.stat().st_size, size=size, oriented=oriented,
                    frames=getattr(image, 'n_frames', 1))


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
                result, _, after = process(job, settings, self.control, lambda _: None)
                if result == 'cancelled':
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


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('OS96 · Image Optimizer')
        self.resize(1440, 820)
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
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([1030, 360])
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
        self.count = QLabel('Drop images or folders here, or use Add images / Add folder')
        ll.addWidget(self.count)
        self.table = ImageTable()
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
        self.resize_box = QWidget()
        form = QFormLayout(self.resize_box)
        self.mode = QComboBox()
        self.mode.addItems(list(RESIZE_HELP))
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
        self.add_options_tab(self.resize_box, 'Resize')
        self.compression_box = QWidget()
        form = QFormLayout(self.compression_box)
        self.lossless = QCheckBox('Lossless compression')
        self.lossless.setChecked(True)
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
        self.threads.setRange(1, min(8, os.cpu_count() or 2))
        self.threads.setValue(min(2, self.threads.maximum()))
        def help_text(text):
            label = HelpLabel(text)
            label.setStyleSheet('color: #58697f; font-size: 11px;')
            form.addRow(label)
            return label
        form.addRow(self.lossless)
        self.lossless_help = help_text('')
        form.addRow('JPEG / WebP quality', self.quality)
        self.quality_help = help_text('1–100: higher values preserve more detail and usually create larger files. Applies only to JPEG and lossy WebP; 100 is still not mathematically lossless.')
        form.addRow('PNG compression', self.png)
        help_text('0–9: higher levels spend more time compressing PNG files. Pixel quality is unchanged at every level.')
        form.addRow(self.metadata)
        help_text('Keeps supported camera information, descriptions, and other metadata. Turn off to remove it. Required orientation and explicitly selected print density are retained.')
        form.addRow(self.color_profile)
        help_text('Keeps embedded ICC color profiles independently of metadata. Recommended: removing a profile may change how colors appear.')
        form.addRow('Parallel images', self.threads)
        help_text('Number of images processed at once. More workers can improve speed but use more RAM and CPU. Use 1 for very large images.')
        note = HelpLabel('Animated / multipage images are skipped. Metadata and color-profile support vary by format.')
        form.addRow(note)
        self.add_options_tab(self.compression_box, 'Optimize')
        self.output_box = QWidget()
        form = QVBoxLayout(self.output_box)
        self.in_place = QCheckBox('Replace originals in place')
        form.addWidget(self.in_place)
        self.output = QLineEdit()
        self.output.setPlaceholderText('Choose output folder…')
        self.browse = QPushButton('Choose folder')
        form.addWidget(self.output)
        form.addWidget(self.browse)
        self.overwrite = QCheckBox('Overwrite existing output files')
        form.addWidget(self.overwrite)
        self.add_options_tab(self.output_box, 'Destination')
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.summary = QLabel('Ready')
        footer.addWidget(self.summary, 1)
        self.pause = QPushButton('Pause')
        self.stop = QPushButton('Stop')
        self.start = QPushButton('Start optimization')
        self.start.setObjectName('primary')
        for button in (self.pause, self.stop, self.start):
            footer.addWidget(button)
        layout.addLayout(footer)
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
        self.lossless.toggled.connect(self.update_options)
        self.in_place.toggled.connect(self.update_options)
        for widget in (self.width, self.height, self.dpi, self.print_width, self.print_height, self.quality, self.png):
            widget.valueChanged.connect(self.schedule_estimates)
        self.dimension_mode.currentTextChanged.connect(self.update_options)
        self.print_unit.currentTextChanged.connect(self.schedule_estimates)
        self.metadata.toggled.connect(self.schedule_estimates)
        self.color_profile.toggled.connect(self.schedule_estimates)
        self.update_options()
        self.update_remove()

    def add_options_tab(self, options, title):
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
        self.count.setText(f'{len(self.jobs):,} images · Drop images or folders to add more'
                           if self.jobs else 'Drop images or folders here, or use Add images / Add folder')

    def update_options(self, *_):
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
        self.compression_box.layout().setRowVisible(self.quality, not self.lossless.isChecked())
        self.compression_box.layout().setRowVisible(self.quality_help, not self.lossless.isChecked())
        if self.lossless.isChecked():
            self.lossless_help.setText('PNG and WebP preserve pixel quality. JPEGs in Keep original mode preserve their compressed pixels, including when removing metadata or profiles. Resized JPEGs are reencoded at quality 100 and are not mathematically lossless. Resizing changes pixels in every format.')
        else:
            self.lossless_help.setText('Set JPEG / WebP quality below to control the size/detail tradeoff. PNG, TIFF, and BMP do not use this quality setting.')
        for widget in (self.output, self.browse, self.overwrite):
            widget.setEnabled(not self.in_place.isChecked())
        self.schedule_estimates()

    def preview_settings(self):
        return Settings(output=Path('.'), resize=self.mode.currentText(),
                        width=self.width.value(), height=self.height.value(),
                        dimension_mode=self.dimension_mode.currentText(),
                        dpi=self.dpi.value(), print_width=self.print_width.value(),
                        print_height=self.print_height.value(), print_unit=self.print_unit.currentText(),
                        lossless=self.lossless.isChecked(),
                        quality=self.quality.value(), png_level=self.png.value(), metadata=self.metadata.isChecked(),
                        color_profile=self.color_profile.isChecked())

    def schedule_estimates(self, *_):
        self.generation += 1
        self.estimate_timer.stop()
        if self.estimator and self.estimator.isRunning():
            self.estimator.control.stop()
        if self.busy:
            return
        settings = self.preview_settings()
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
        if self.jobs:
            self.estimate_timer.start()

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
        label = f'≈ {file_size(size)}' if size is not None else 'Unavailable'
        item.setText(f'{dimensions}\n{label}' if dimensions else label)
        item.setToolTip(error or 'Trial encode using current settings; actual output may vary if the source changes.')

    def estimates_finished(self):
        if self.closing:
            self.close()

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Select images', '', 'Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp)')
        self.scan(paths)

    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Select input folder')
        if path:
            self.scan([path])

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

    def set_busy(self, busy):
        self.busy = busy
        self.table.drop_enabled = not busy
        self.update_remove()
        if busy:
            self.estimate_timer.stop()
            self.generation += 1
            if self.estimator and self.estimator.isRunning():
                self.estimator.control.stop()
        for widget in (self.add_files, self.add_folder, self.clear, self.resize_box,
                       self.compression_box, self.output_box, self.start):
            widget.setEnabled(not busy)
        self.pause.setEnabled(busy)
        self.stop.setEnabled(busy)
        if not busy:
            self.schedule_estimates()

    def start_batch(self):
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
        self.pause.setText('Pause')
        self.progress.setRange(0, len(self.jobs))
        self.progress.setValue(0)
        for i in range(len(self.jobs)):
            self.table.item(i, 1).setText('Queued')
        self.worker = Worker(self.jobs.copy(), settings)
        self.worker.status.connect(self.image_status)
        self.worker.progress.connect(self.batch_progress)
        self.worker.result.connect(self.completed)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def image_status(self, index, message):
        self.table.item(index, 1).setText(message)
        self.table.item(index, 1).setToolTip(message)

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

    def stop_batch(self):
        if self.worker:
            self.worker.control.stop()
            self.pause.setEnabled(False)
            self.stop.setEnabled(False)
            self.summary.setText('Stopping after current encoding operations…')

    def completed(self, totals):
        if 'fatal' in totals:
            QMessageBox.critical(self, 'Processing error', totals['fatal'])
            self.summary.setText('Processing failed')
            return
        stopped = self.worker.control.stopped
        for i in range(len(self.jobs)):
            if self.table.item(i, 1).text() == 'Queued':
                self.image_status(i, 'Not processed · stopped')
        saved = (totals['before'] - totals['after']) / 1048576
        self.summary.setText(f"{'Stopped' if stopped else 'Complete'} · {totals['done']} done · {totals['skipped']} skipped · {totals['error']} errors · {saved:.2f} MB saved")

    def closeEvent(self, event):
        if (self.worker and self.worker.isRunning()) or (self.scanner and self.scanner.isRunning()):
            QMessageBox.information(self, 'Work in progress', 'Stop processing and wait for active operations to finish before closing.')
            event.ignore()
        elif self.estimator and self.estimator.isRunning():
            self.closing = True
            self.estimate_timer.stop()
            self.estimator.control.stop()
            event.ignore()
        else:
            event.accept()


def main():
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
    app.setStyleSheet('''
        QWidget { font-family: "Segoe UI", "Helvetica Neue"; font-size: 12px; }
        QMainWindow { background: #f4f6fa; }
        QLabel#title { font-size: 29px; font-weight: 700; color: #17283f; }
        QPushButton { padding: 9px 14px; border-radius: 6px; border: 1px solid #ccd5e1; background: white; }
        QPushButton:hover { background: #e8effa; }
        QPushButton#primary { background: #2563eb; color: white; border: none; font-weight: 600; }
        QPushButton:disabled { color: #939ba7; background: #edf0f5; }
        QTableWidget { border: 1px solid #d9e0ea; background: white; alternate-background-color: #f7f9fc; }
        QHeaderView::section { background: #e9eef6; padding: 8px; border: none; }
        QTabWidget::pane { border: 1px solid #d9e0ea; border-radius: 6px; background: white; }
        QTabBar::tab { padding: 9px 12px; background: #e9eef6; color: #345174; border: 1px solid #d9e0ea; }
        QTabBar::tab:selected { background: white; color: #2563eb; font-weight: 600; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 5px; }
        QProgressBar { border: none; border-radius: 5px; background: #e0e7f1; text-align: center; height: 19px; }
        QProgressBar::chunk { background: #5390ed; border-radius: 5px; }
    ''')
    window = Window()
    window.show()
    sys.exit(app.exec())
