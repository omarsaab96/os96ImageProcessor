"""Desktop preferences, reports, and an isolated full-resolution comparison."""
import csv
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QSettings, QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QPushButton, QHBoxLayout, QComboBox, QInputDialog,
    QFileDialog, QMessageBox, QDialog, QVBoxLayout, QLabel, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView)

from .engine import process, Control, Job, web_colors


class PreviewWorker(QThread):
    result = Signal(object, object, str)

    def __init__(self, job, settings):
        super().__init__()
        self.job, self.settings, self.control = job, settings, Control()

    def run(self):
        try:
            with tempfile.TemporaryDirectory(prefix='os96-compare-') as folder:
                target = Path(folder) / self.job.source.name
                messages = []
                result = process(Job(self.job.source, Path(target.name)),
                    replace(self.settings, output=Path(folder), in_place=False,
                            only_smaller=False, overwrite=True), self.control, messages.append)
                if result[0] != 'done':
                    raise ValueError(messages[-1] if messages else 'Preview cancelled')
                images = []
                for path in (self.job.source, target):
                    with Image.open(path) as source:
                        if source.width * source.height > 25_000_000:
                            raise ValueError('Full-resolution comparison supports up to 25 megapixels per image. Processing supports larger images.')
                        with ImageOps.exif_transpose(source) as oriented:
                            with web_colors(oriented) as display:
                                with display.convert('RGBA') as rgba:
                                    images.append(QImage(rgba.tobytes(), rgba.width, rgba.height,
                                                         QImage.Format_RGBA8888).copy())
                if not self.control.stopped:
                    self.result.emit(*images, f'Original: {self.job.source.stat().st_size:,} bytes | Output: {target.stat().st_size:,} bytes')
        except Exception as exc:
            self.result.emit(None, None, str(exc))


class WorkflowMixin:
    def setup_workflow(self, persist, left, right, preferences=None):
        self.persist = persist
        self.preferences = preferences if preferences is not None else QSettings('OS96', 'ImageOptimizer')
        self.preview_worker = None
        self.report_rows, self.batch_rows, self.report_totals = [], [], {}
        try:
            self.preset_values = json.loads(str(self.preferences.value('presets', '{}'))) if persist else {}
            if not isinstance(self.preset_values, dict):
                self.preset_values = {}
        except (TypeError, ValueError):
            self.preset_values = {}
        self.preset = QComboBox()
        self.preset.addItems(['Choose preset…', *sorted(self.preset_values)])
        save = QPushButton('Save preset')
        save.clicked.connect(self.save_preset)
        self.preset.textActivated.connect(self.apply_preset)
        right.insertWidget(0, self.preset)
        right.insertWidget(1, save)
        row = QHBoxLayout()
        compare = QPushButton('Compare selected')
        retry = QPushButton('Retry failed')
        report = QPushButton('Batch report')
        open_output = QPushButton('Open output folder')
        for button, action in ((compare, self.compare_selected), (retry, self.retry_failed),
                               (report, self.show_report), (open_output, self.open_output)):
            row.addWidget(button)
            button.clicked.connect(action)
        left.addLayout(row)
        self.workflow_controls = [compare, retry, self.preset, save]
        self.web.setToolTip('Converts tagged colors to sRGB and removes descriptive metadata. Uses the selected compression strategy.')
        self.web_help.setText('Converts tagged colors to sRGB and removes descriptive metadata. Untagged RGB is assumed sRGB. Filenames and formats are retained. Enable Only save smaller to skip larger results.')
        if persist:
            try:
                self.apply_values(json.loads(str(self.preferences.value('settings', '{}'))))
                self.output.setText(str(self.preferences.value('destination', '')))
            except (TypeError, ValueError):
                pass

    def preference_widgets(self):
        return {name: getattr(self, name) for name in ('mode', 'dimension_mode', 'width', 'height',
            'dpi', 'print_width', 'print_height', 'print_unit', 'compression', 'quality', 'png',
            'metadata', 'color_profile', 'web', 'threads', 'only_smaller')}

    def preference_values(self):
        values = {}
        for name, widget in self.preference_widgets().items():
            values[name] = (widget.currentText() if isinstance(widget, QComboBox) else
                            widget.isChecked() if hasattr(widget, 'isChecked') else widget.value())
        return values

    def apply_values(self, values):
        for name, widget in self.preference_widgets().items():
            if name not in values:
                continue
            value = values[name]
            if isinstance(widget, QComboBox):
                if widget.findText(str(value)) >= 0:
                    widget.setCurrentText(str(value))
            elif hasattr(widget, 'setChecked'):
                widget.setChecked(bool(value))
            else:
                widget.setValue(value)

    def save_preferences(self):
        if self.persist:
            self.preferences.setValue('settings', json.dumps(self.preference_values()))
            self.preferences.setValue('destination', self.output.text())
            self.preferences.setValue('presets', json.dumps(self.preset_values))
            self.preferences.sync()

    def save_preset(self):
        name, accepted = QInputDialog.getText(self, 'Save preset', 'Preset name')
        if accepted and name.strip():
            name = name.strip()
            self.preset_values[name] = self.preference_values()
            if self.preset.findText(name) < 0:
                self.preset.addItem(name)
            self.preset.setCurrentText(name)
            self.save_preferences()

    def apply_preset(self, name):
        self.apply_values(self.preset_values.get(name, {}))

    def open_output(self):
        folder = self.last_settings.output if hasattr(self, 'last_settings') and not self.last_settings.in_place else Path(self.output.text())
        if hasattr(self, 'last_settings') and self.last_settings.in_place and self.batch_rows:
            folder = Path(self.batch_rows[0]['source']).parent
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def capture_batch(self, settings):
        self.last_settings = settings
        self.batch_rows = []
        for job in self.jobs:
            try:
                before = job.source.stat().st_size
            except OSError:
                before = 0
            self.batch_rows.append(dict(source=str(job.source), destination=str(job.source if settings.in_place else settings.output / job.relative), before=before))
        self.save_preferences()

    def finish_report(self, totals):
        self.report_totals = totals.copy()
        self.report_rows = []
        for index, original in enumerate(self.batch_rows):
            row = original.copy()
            row['status'] = self.table.item(index, 1).text()
            try:
                row['after'] = Path(row['destination']).stat().st_size if row['status'] == 'Done' else ''
            except OSError:
                row['after'] = ''
            row['saved'] = row['before'] - row['after'] if isinstance(row['after'], int) else ''
            self.report_rows.append(row)

    def show_report(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Batch report')
        dialog.resize(850, 500)
        layout = QVBoxLayout(dialog)
        totals = self.report_totals
        saved = totals.get('before', 0) - totals.get('after', 0)
        layout.addWidget(QLabel(f"{totals.get('done', 0)} completed · {totals.get('skipped', 0)} skipped · "
                               f"{totals.get('error', 0)} errors · {saved:,} bytes saved"))
        table = QTableWidget(len(self.report_rows), 5)
        table.setHorizontalHeaderLabels(['File', 'Status / error', 'Original bytes', 'Output bytes', 'Saved bytes'])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setColumnWidth(0, 160)
        for index, row in enumerate(self.report_rows):
            values = [Path(row['source']).name, row['status'], row['before'], row['after'], row['saved']]
            for column, value in enumerate(values):
                item = QTableWidgetItem(f'{value:,}' if isinstance(value, int) else str(value))
                item.setToolTip(str(value))
                table.setItem(index, column, item)
            table.item(index, 0).setToolTip(f"Source: {row['source']}\nDestination: {row['destination']}")
        table.resizeRowsToContents()
        layout.addWidget(table)
        export = QPushButton('Export CSV')
        layout.addWidget(export)
        def save_csv():
            path, _ = QFileDialog.getSaveFileName(dialog, 'Export report', 'os96-report.csv', 'CSV (*.csv)')
            if path:
                try:
                    with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
                        writer = csv.DictWriter(stream, fieldnames=['source', 'destination', 'before', 'status', 'after', 'saved'])
                        writer.writeheader()
                        for row in self.report_rows:
                            writer.writerow({key: "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value for key, value in row.items()})
                except OSError as exc:
                    QMessageBox.warning(dialog, 'Export failed', str(exc))
        export.clicked.connect(save_csv)
        dialog.exec()

    def retry_failed(self):
        if self.busy:
            return
        indices = [i for i in range(len(self.jobs)) if self.table.item(i, 1).text().startswith(('Error', 'Cancelled', 'Not processed'))]
        if not indices:
            self.summary.setText('No failed or cancelled files to retry')
            return
        entries = [(self.jobs[i], self.info[i]) for i in indices]
        self.scanned([x[0] for x in entries], [], [x[1] for x in entries])
        self.start_batch()

    def compare_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if self.busy or not rows or (self.preview_worker and self.preview_worker.isRunning()):
            return
        self.preview_worker = PreviewWorker(self.jobs[rows[0].row()], self.preview_settings())
        self.preview_worker.result.connect(self.show_comparison)
        self.preview_worker.finished.connect(lambda: self.set_busy(False))
        self.set_busy(True)
        self.pause.setEnabled(False)
        self.stop.setEnabled(False)
        self.summary.setText('Encoding full-resolution comparison…')
        self.preview_worker.start()

    def show_comparison(self, original, output, details):
        if original is None:
            self.summary.setText(details)
            return
        self.summary.setText('Comparison ready')
        dialog = QDialog(self)
        dialog.setWindowTitle('Before / after — 100% pixel view')
        dialog.resize(1100, 700)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(details))
        layout.addWidget(QLabel('Left: original | Right: encoded output. Scrollbars are linked. Display colors are converted to sRGB.'))
        zoom = QComboBox()
        zoom.addItems(['100%', '50%', '25%'])
        layout.addWidget(zoom)
        row = QHBoxLayout()
        layout.addLayout(row)
        views, labels = [], []
        for picture in (original, output):
            view = QScrollArea()
            label = QLabel()
            label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            view.setWidget(label)
            row.addWidget(view)
            views.append(view)
            labels.append(label)
        def resize_images():
            scale = int(zoom.currentText()[:-1]) / 100
            for label, picture in zip(labels, (original, output)):
                pixmap = QPixmap.fromImage(picture)
                if scale != 1:
                    pixmap = pixmap.scaled(max(1, round(picture.width() * scale)), max(1, round(picture.height() * scale)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pixmap.setDevicePixelRatio(dialog.devicePixelRatioF())
                label.setPixmap(pixmap)
                label.resize(pixmap.deviceIndependentSize().toSize())
        for getter in ('horizontalScrollBar', 'verticalScrollBar'):
            a, b = getattr(views[0], getter)(), getattr(views[1], getter)()
            a.valueChanged.connect(b.setValue)
            b.valueChanged.connect(a.setValue)
        zoom.currentIndexChanged.connect(resize_images)
        resize_images()
        dialog.exec()
