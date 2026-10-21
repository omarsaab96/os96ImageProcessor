import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QItemSelectionModel, QMimeData, QUrl, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from optimizer.app import Window, image_info, file_size, output_size, dropped_paths
from optimizer.engine import discover


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_headers_respect_orientation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rotated.jpg'
            exif = Image.Exif()
            exif[274] = 6
            Image.new('RGB', (80, 40)).save(path, exif=exif)
            info = image_info(path)
            self.assertEqual(info['size'], (80, 40))
            self.assertEqual(info['oriented'], (40, 80))
            self.assertEqual(info['bytes'], path.stat().st_size)
            self.assertEqual((info['thumbnail'].width(), info['thumbnail'].height()), (20, 40))

    def test_live_estimate_matches_trial_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            Image.new('RGB', (160, 80), 'navy').save(path)
            original = path.read_bytes()
            jobs, _ = discover([path])
            window = Window()
            window.compression.setCurrentText('Lossless')
            window.scanned(jobs, [], [image_info(path)])
            self.assertFalse(window.table.item(0, 0).icon().isNull())
            self.assertEqual(window.table.item(0, 0).text(), 'image.png')
            window.mode.setCurrentText('By dimensions')
            window.resize_enabled.setChecked(True)
            window.dimension_mode.setCurrentText('Exact')
            window.width.setValue(32)
            window.height.setValue(24)
            self.assertEqual(window.table.item(0, 3).text(), '32 × 24 px\n≈ …')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.app.processEvents()
                if window.table.item(0, 3).text().splitlines()[-1].startswith('≈ ') and not window.table.item(0, 3).text().endswith('…'):
                    break
                time.sleep(.01)
            self.assertTrue(window.table.item(0, 3).text().splitlines()[-1].startswith('≈ '))
            self.assertFalse(window.table.item(0, 3).text().endswith('…'))
            self.assertTrue(window.table.item(0, 3).text().startswith('32 × 24 px\n'))
            self.assertEqual(window.table.item(0, 2).text(), f'160 × 80 px\n{file_size(len(original))}')
            self.assertEqual(path.read_bytes(), original)
            window.estimate_timer.stop()
            if window.estimator:
                window.estimator.control.stop()
                window.estimator.wait(5000)
            window.close()

    def wait_scan(self, window):
        deadline = time.monotonic() + 5
        while window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(window.busy)
        window.estimate_timer.stop()

    def test_resize_modes_show_relevant_fields_and_behavior(self):
        window = Window()
        self.assertEqual([window.mode.itemText(i) for i in range(window.mode.count())],
                         ['By dimensions', 'By resolution'])
        self.assertFalse(window.width.isEnabled())
        self.assertFalse(window.height.isEnabled())
        self.assertFalse(window.resize_enabled.isChecked())
        window.mode.setCurrentText('By dimensions')
        window.resize_enabled.setChecked(True)
        for option, width_visible, height_visible, explanation in [
            ('Exact', True, True, 'stretching'), ('Height', False, True, 'calculates its width'),
            ('Width', True, False, 'calculates its height'), ('Auto', True, True, 'portrait')]:
            window.dimension_mode.setCurrentText(option)
            self.assertEqual(not window.width.isHidden(), width_visible)
            self.assertEqual(not window.height.isHidden(), height_visible)
            self.assertIn(explanation, window.resize_note.text())
            self.assertTrue(window.dimension_mode.itemData(window.dimension_mode.currentIndex(), Qt.ToolTipRole))
            self.assertEqual(window.preview_settings().dimension_mode, option)
        window.mode.setCurrentText('By resolution')
        self.assertTrue(window.width.isHidden())
        self.assertTrue(window.height.isHidden())
        self.assertFalse(window.dpi.isHidden())
        self.assertFalse(window.print_width.isHidden())
        self.assertIn('DPI', window.resize_note.text())
        window.close()

    def test_resize_and_compression_are_independent_steps(self):
        from unittest.mock import patch
        window = Window()
        self.assertFalse(window.resize_enabled.isChecked())
        self.assertTrue(window.compression_enabled.isChecked())
        window.resize_enabled.setChecked(True)
        self.assertEqual(window.preview_settings().resize, 'By dimensions')
        self.assertTrue(window.preview_settings().compress)
        window.compression_enabled.setChecked(False)
        self.assertFalse(window.preview_settings().smart)
        self.assertFalse(window.preview_settings().compress)
        self.assertTrue(window.preview_settings().lossless)
        self.assertFalse(window.compression_box.isEnabled())
        self.assertTrue(window.resize_box.isEnabled())
        window.resize_enabled.setChecked(False)
        self.assertEqual(window.preview_settings().resize, 'Keep original')
        self.assertFalse(window.estimate_timer.isActive())
        with patch('optimizer.app.QMessageBox.information') as message:
            window.start_batch()
            message.assert_called_once()
        for widget in (window.metadata, window.color_profile, window.threads):
            self.assertIs(widget.parentWidget(), window.settings_box)
        self.assertEqual([window.options_tabs.tabText(i) for i in range(3)],
                         ['Resize', 'Compression', 'Destination'])
        window.close()

    def test_optimize_quality_visibility_and_independent_controls(self):
        window = Window()
        window.compression.setCurrentText('Lossless')
        form = window.compression_box.layout()
        label = form.labelForField(window.quality)
        self.assertTrue(window.quality.isHidden())
        self.assertTrue(label.isHidden())
        self.assertTrue(window.quality_help.isHidden())
        window.compression.setCurrentText('Manual quality')
        self.assertFalse(window.quality.isHidden())
        self.assertFalse(label.isHidden())
        self.assertFalse(window.quality_help.isHidden())
        window.quality.setValue(72)
        window.compression.setCurrentText('Lossless')
        window.compression.setCurrentText('Manual quality')
        self.assertEqual(window.quality.value(), 72)
        window.metadata.setChecked(False)
        self.assertFalse(window.preview_settings().metadata)
        self.assertTrue(window.preview_settings().color_profile)
        window.color_profile.setChecked(False)
        window.metadata.setChecked(True)
        self.assertTrue(window.preview_settings().metadata)
        self.assertFalse(window.preview_settings().color_profile)
        window.close()

    def test_web_overrides_without_losing_manual_preferences(self):
        window = Window()
        window.compression.setCurrentText('Lossless')
        window.web.setChecked(True)
        self.assertTrue(window.preview_settings().web)
        self.assertFalse(window.preview_settings().smart)
        self.assertTrue(window.compression.isEnabled())
        for field in (window.metadata, window.color_profile):
            self.assertFalse(field.isEnabled())
        window.web.setChecked(False)
        self.assertFalse(window.preview_settings().smart)
        self.assertTrue(window.metadata.isChecked())
        self.assertTrue(window.metadata.isEnabled())
        self.assertTrue(window.color_profile.isEnabled())
        window.web.setChecked(True)
        window.compression.setCurrentText('Manual quality')
        self.assertTrue(window.preview_settings().web)
        self.assertFalse(window.preview_settings().smart)
        self.assertFalse(window.preview_settings().lossless)
        self.assertFalse(window.quality.isHidden())
        window.compression.setCurrentText('Automatic')
        self.assertTrue(window.preview_settings().smart)
        self.assertTrue(window.quality.isHidden())
        window.close()

    def test_automatic_compression_shows_estimate_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.jpg'
            Image.new('RGB', (80, 40), 'navy').save(path)
            jobs, _ = discover([path])
            window = Window()
            window.scanned(jobs, [], [image_info(path)])
            window.schedule_estimates()
            self.assertTrue(window.estimate_timer.isActive())
            window.estimate_timer.stop()
            window.launch_estimates()
            deadline = time.monotonic() + 5
            while window.estimator.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.app.processEvents()
            label = window.table.item(0, 3).text().splitlines()[-1]
            self.assertTrue(label.startswith('≈ '))
            self.assertNotIn('…', label)
            self.assertIn('small preview', window.table.item(0, 3).toolTip())
            window.close()

    def test_batch_replaces_placeholder_for_done_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'image.jpg'
            output = root / 'export'
            Image.new('RGB', (80, 40), 'navy').save(path)
            jobs, _ = discover([path])
            window = Window()
            window.scanned(jobs, [], [image_info(path)])
            window.schedule_estimates()
            window.output.setText(str(output))
            for status in ('Done', 'Skipped'):
                window.start_batch()
                self.assertTrue(window.start.isHidden())
                self.assertFalse(window.pause.isHidden())
                self.assertFalse(window.stop.isHidden())
                deadline = time.monotonic() + 10
                while window.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertFalse(window.busy)
                self.assertTrue(window.table.item(0, 1).text().startswith(status))
                expected = output_size((output / path.name).stat().st_size, len(path.read_bytes()))
                self.assertEqual(window.table.item(0, 3).text().splitlines()[-1], expected)
                self.assertNotIn('Size after processing', window.table.item(0, 3).text())
                self.assertEqual(window.progress.value(), 0)
                self.assertFalse(window.loading_timer.isActive())
                self.assertFalse(window.start.isHidden())
                self.assertTrue(window.pause.isHidden())
                self.assertTrue(window.stop.isHidden())
                self.assertEqual(window.percentage.text(), '0%')
            window.close()

    def test_loading_animates_and_output_percentage_handles_growth(self):
        window = Window()
        window.set_busy(True)
        self.assertTrue(window.loading_timer.isActive())
        first = window.progress.phase
        window.animate_loading()
        self.assertNotEqual(first, window.progress.phase)
        self.assertTrue(window.progress.animating)
        self.assertEqual(window.progress.maximum(), 0)
        window.set_busy(False, refresh=False)
        self.assertEqual(window.progress.value(), 0)
        self.assertEqual(window.activity.text(), '')
        self.assertFalse(window.progress.animating)
        self.assertEqual(output_size(500, 1000), '500 B (-50.0%)')
        self.assertEqual(output_size(1500, 1000, estimated=True), '≈ 1.5 KB (+50.0%)')
        self.assertEqual(output_size(500, 0), '500 B')
        window.close()

    def test_optimize_help_shrinks_when_lossless_is_toggled(self):
        window = Window()
        window.compression.setCurrentText('Lossless')
        window.resize(1000, 650)
        window.options_tabs.setCurrentIndex(1)
        window.show()
        for _ in range(10):
            self.app.processEvents()
        long_height = window.lossless_help.height()
        for _ in range(3):
            window.compression.setCurrentText('Manual quality')
            for _ in range(10):
                self.app.processEvents()
            self.assertLess(window.lossless_help.height(), long_height)
            gap = window.quality.y() - (window.lossless_help.y() + window.lossless_help.height())
            self.assertGreaterEqual(gap, 0)
            self.assertLessEqual(gap, 12)
            window.compression.setCurrentText('Lossless')
            for _ in range(10):
                self.app.processEvents()
        window.close()

    def test_remove_multiple_and_keep_exclusions_on_add(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f'{name}.png' for name in ('a', 'b', 'c', 'd')]
            for path in paths:
                Image.new('RGB', (40, 20)).save(path)
            window = Window()
            window.scan([root])
            self.wait_scan(window)
            for row in (0, 2):
                window.table.selectionModel().select(window.table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
            self.assertTrue(window.remove.isEnabled())
            old_generation = window.generation
            window.remove.click()
            self.assertEqual([job.source.name for job in window.jobs], ['b.png', 'd.png'])
            window.estimated(old_generation, 3, 99, '')  # Stale row must be ignored.
            self.assertTrue(all(path.exists() for path in paths))
            # Adding an unrelated image must not resurrect exclusions from a folder.
            window.scan([paths[3]])
            self.wait_scan(window)
            self.assertEqual([job.source.name for job in window.jobs], ['b.png', 'd.png'])
            window.scan([paths[0]])
            self.wait_scan(window)
            self.assertEqual([job.source.name for job in window.jobs], ['a.png', 'b.png', 'd.png'])
            window.show()
            window.activateWindow()
            window.table.setFocus()
            self.app.processEvents()
            window.table.selectRow(0)
            QTest.keyClick(window.table, Qt.Key_Delete)
            self.assertEqual(len(window.jobs), 2)
            window.set_busy(True)
            window.table.selectRow(0)
            window.remove_selected()
            self.assertEqual(len(window.jobs), 2)
            self.assertFalse(window.remove.isEnabled())
            window.set_busy(False)
            window.clear_jobs()
            window.close()

    def test_drop_only_queues_and_keeps_original(self):
        for surface in ('table', 'window'):
            with self.subTest(surface=surface), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / 'image.jpg'
                Image.new('RGB', (100, 80), 'navy').save(path, quality=95)
                original = path.read_bytes()
                window = Window()
                self.assertEqual(window.compression.currentText(), 'Automatic')
                window.output.setText(str(root / 'output'))
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(path))])
                event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                (window.table if surface == 'table' else window).dropEvent(event)
                deadline = time.monotonic() + 10
                while window.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.app.processEvents()
                self.assertFalse(window.busy)
                self.assertIsNone(window.worker)
                self.assertFalse((root / 'output' / path.name).exists())
                self.assertEqual(window.table.item(0, 1).text(), 'Ready')
                self.assertEqual(path.read_bytes(), original)
                window.close()

    def test_drop_files_folders_and_busy_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'image.png'
            Image.new('RGB', (40, 20)).save(path)
            text = root / 'notes.txt'
            text.write_text('unsupported')
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(root)), QUrl.fromLocalFile(str(path)),
                          QUrl.fromLocalFile(str(text)), QUrl('https://example.com/image.png')])
            self.assertEqual(dropped_paths(mime), [root, path])
            window = Window()
            def drop():
                return QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            event = drop()
            window.table.dropEvent(event)
            self.assertTrue(event.isAccepted())
            self.wait_scan(window)
            self.assertEqual(len(window.jobs), 1)
            window.set_busy(True)
            event = drop()
            window.table.dropEvent(event)
            self.assertFalse(event.isAccepted())
            event = drop()
            window.dropEvent(event)
            self.assertFalse(event.isAccepted())
            window.set_busy(False)
            window.clear_jobs()
            event = drop()
            window.dropEvent(event)
            self.assertTrue(event.isAccepted())
            self.wait_scan(window)
            self.assertEqual(len(window.jobs), 1)
            window.clear_jobs()
            window.close()
