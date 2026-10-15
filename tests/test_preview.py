import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QItemSelectionModel, QMimeData, QUrl, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from optimizer.app import Window, image_info, file_size, dropped_paths
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

    def test_live_estimate_matches_trial_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            Image.new('RGB', (160, 80), 'navy').save(path)
            original = path.read_bytes()
            jobs, _ = discover([path])
            window = Window()
            window.scanned(jobs, [], [image_info(path)])
            window.mode.setCurrentText('By dimensions')
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
                         ['Keep original', 'By dimensions', 'By resolution'])
        self.assertTrue(window.width.isHidden())
        self.assertTrue(window.height.isHidden())
        self.assertTrue(window.dimension_mode.isHidden())
        self.assertIn('original pixel dimensions', window.resize_note.text())
        window.mode.setCurrentText('By dimensions')
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

    def test_optimize_quality_visibility_and_independent_controls(self):
        window = Window()
        form = window.compression_box.layout()
        label = form.labelForField(window.quality)
        self.assertTrue(window.quality.isHidden())
        self.assertTrue(label.isHidden())
        self.assertTrue(window.quality_help.isHidden())
        window.lossless.setChecked(False)
        self.assertFalse(window.quality.isHidden())
        self.assertFalse(label.isHidden())
        self.assertFalse(window.quality_help.isHidden())
        window.quality.setValue(72)
        window.lossless.setChecked(True)
        window.lossless.setChecked(False)
        self.assertEqual(window.quality.value(), 72)
        window.metadata.setChecked(False)
        self.assertFalse(window.preview_settings().metadata)
        self.assertTrue(window.preview_settings().color_profile)
        window.color_profile.setChecked(False)
        window.metadata.setChecked(True)
        self.assertTrue(window.preview_settings().metadata)
        self.assertFalse(window.preview_settings().color_profile)
        window.close()

    def test_optimize_help_shrinks_when_lossless_is_toggled(self):
        window = Window()
        window.resize(1000, 650)
        window.options_tabs.setCurrentIndex(1)
        window.show()
        for _ in range(10):
            self.app.processEvents()
        long_height = window.lossless_help.height()
        for _ in range(3):
            window.lossless.setChecked(False)
            for _ in range(10):
                self.app.processEvents()
            self.assertLess(window.lossless_help.height(), long_height)
            gap = window.quality.y() - (window.lossless_help.y() + window.lossless_help.height())
            self.assertGreaterEqual(gap, 0)
            self.assertLessEqual(gap, 12)
            window.lossless.setChecked(True)
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
