import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageCms
from PySide6.QtWidgets import QApplication
from optimizer.app import Window, image_info
from optimizer.workflow import PreviewWorker
from optimizer.engine import Job, Settings, Control, process, run_batch


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.png'
        Image.new('RGB', (80, 40), 'navy').save(self.source)
        self.job = Job(self.source, Path(self.source.name))
        self.settings = Settings(self.root / 'out', resize='By dimensions', width=300, height=200)

    def tearDown(self):
        self.temp.cleanup()

    def test_enlargement_is_written_unless_smaller_only(self):
        self.assertEqual(process(self.job, self.settings, Control(), lambda _: None)[0], 'done')
        with Image.open(self.settings.output / self.job.relative) as result:
            self.assertEqual(result.size, (300, 200))

    def test_no_hardlinks_external_drive(self):
        with patch('optimizer.engine.os.link', side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            self.assertEqual(process(self.job, self.settings, Control(), lambda _: None)[0], 'done')
        self.assertFalse(list(self.settings.output.glob('.os96-*')))

    def test_disk_full_preserves_original(self):
        from dataclasses import replace
        original = self.source.read_bytes()
        with patch('PIL.Image.Image.save', side_effect=OSError(errno.ENOSPC, 'disk full')):
            result = process(self.job, replace(self.settings, in_place=True), Control(), lambda _: None)
        self.assertEqual(result[0], 'error')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.os96-*')))

    def test_permission_error_isolated_and_no_replacement(self):
        original = self.source.read_bytes()
        with patch('optimizer.engine.tempfile.mkstemp', side_effect=PermissionError('denied')):
            totals = run_batch([self.job], self.settings, Control(), lambda *_: None, lambda *_: None)
        self.assertEqual(totals['error'], 1)
        self.assertEqual(self.source.read_bytes(), original)

    def test_destination_race_preserves_existing(self):
        destination = self.settings.output / self.job.relative
        def race(source, target):
            target.write_bytes(b'other application')
            raise FileExistsError('appeared during encode')
        with patch('optimizer.engine.os.link', side_effect=race):
            self.assertEqual(process(self.job, self.settings, Control(), lambda _: None)[0], 'error')
        self.assertEqual(destination.read_bytes(), b'other application')

    def test_path_escape_rejected(self):
        job = Job(self.source, Path('../escape.png'))
        self.assertEqual(process(job, self.settings, Control(), lambda _: None)[0], 'error')
        self.assertFalse((self.root / 'escape.png').exists())

    def test_invalid_encoder_result_cannot_replace_original(self):
        from dataclasses import replace
        original = self.source.read_bytes()
        with patch('PIL.Image.Image.save', side_effect=lambda path, **kwargs: Path(path).write_bytes(b'bad')):
            self.assertEqual(process(self.job, replace(self.settings, in_place=True), Control(), lambda _: None)[0], 'error')
        self.assertEqual(self.source.read_bytes(), original)

    def test_web_output_tagged_srgb_without_fallback(self):
        from dataclasses import replace
        source = self.root / 'tagged.jpg'
        # A tagged RGB fixture still exercises profile conversion and output tagging.
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB', (80, 40), 'red').save(source, icc_profile=srgb)
        settings = replace(self.settings, web=True, resize='Keep original')
        self.assertEqual(process(Job(source, Path(source.name)), settings, Control(), lambda _: None)[0], 'done')
        with Image.open(settings.output / source.name) as result:
            from io import BytesIO
            self.assertIn('sRGB', ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(BytesIO(result.info['icc_profile']))))

    def test_report_capture(self):
        window = Window()
        window.width.setValue(777)
        values = window.preference_values()
        window.width.setValue(1)
        window.apply_values(values)
        self.assertEqual(window.width.value(), 777)
        window.scanned([self.job], [], [image_info(self.source)])
        window.capture_batch(self.settings)
        window.table.item(0, 1).setText('Error · readable failure')
        window.finish_report({'error': 1})
        self.assertIn('readable failure', window.report_rows[0]['status'])
        self.assertEqual(window.report_rows[0]['before'], self.source.stat().st_size)
        window.close()

    def test_comparison_uses_full_resolution_and_preserves_source(self):
        original = self.source.read_bytes()
        results = []
        worker = PreviewWorker(self.job, self.settings)
        worker.result.connect(lambda *args: results.append(args))
        worker.run()
        self.assertEqual(results[0][0].width(), 80)
        self.assertEqual(results[0][1].width(), 300)
        self.assertEqual(self.source.read_bytes(), original)

    def test_large_comparison_scales_display_without_rejecting_source(self):
        source = self.root / 'large.jpg'
        with Image.new('RGB', (6000, 4500), 'navy') as image:
            image.save(source, quality=85)
        original = source.read_bytes()
        results = []
        worker = PreviewWorker(Job(source, Path(source.name)), Settings(self.root / 'unused', compress=False))
        worker.result.connect(lambda *args: results.append(args))
        worker.run()
        self.assertIsNotNone(results[0][0])
        for image in results[0][:2]:
            self.assertLessEqual(image.width() * image.height(), 4_000_000)
            self.assertLess(float(image.text('display_scale')), 1)
        self.assertIn('processing uses full resolution', results[0][2])
        self.assertEqual(source.read_bytes(), original)

    def test_preferences_survive_restart_without_destructive_flags(self):
        from PySide6.QtCore import QSettings
        preferences = QSettings(str(self.root / 'settings.ini'), QSettings.IniFormat)
        window = Window(persist=True, preferences=preferences)
        window.width.setValue(1234)
        window.compression.setCurrentText('Lossless')
        window.output.setText(str(self.root / 'destination'))
        window.in_place.setChecked(True)
        window.overwrite.setChecked(True)
        window.close()
        restored = Window(persist=True, preferences=preferences)
        self.assertEqual(restored.width.value(), 1234)
        self.assertEqual(restored.compression.currentText(), 'Automatic')
        self.assertEqual(restored.strategy_label.text(), 'Compression: Automatic')
        restored.compression.setCurrentText('Manual quality')
        self.assertEqual(restored.strategy_label.text(), 'Compression: Manual quality')
        self.assertEqual(restored.output.text(), str(self.root / 'destination'))
        self.assertFalse(restored.in_place.isChecked())
        self.assertFalse(restored.overwrite.isChecked())
        restored.close()

    def test_retry_runs_only_failed_entries(self):
        good = self.root / 'done.png'
        Image.new('RGB', (20, 20)).save(good)
        jobs = [self.job, Job(good, Path(good.name))]
        window = Window()
        window.scanned(jobs, [], [image_info(job.source) for job in jobs])
        window.table.item(0, 1).setText('Error · temporary failure')
        window.table.item(1, 1).setText('Done')
        with patch.object(window, 'start_batch') as start:
            window.retry_failed()
            start.assert_called_once()
        self.assertEqual([job.source for job in window.jobs], [self.source])
        window.close()

    def test_enabled_steps_survive_restart(self):
        from PySide6.QtCore import QSettings
        preferences = QSettings(str(self.root / 'steps.ini'), QSettings.IniFormat)
        window = Window(persist=True, preferences=preferences)
        window.resize_enabled.setChecked(True)
        window.compression_enabled.setChecked(False)
        window.width.setValue(1234)
        window.close()
        restored = Window(persist=True, preferences=preferences)
        self.assertTrue(restored.resize_enabled.isChecked())
        self.assertFalse(restored.compression_enabled.isChecked())
        self.assertFalse(restored.preview_settings().compress)
        self.assertEqual(restored.preview_settings().width, 1234)
        restored.close()

    def test_unicode_deep_path_and_mixed_batch(self):
        folder = self.root
        for _ in range(6):
            folder = folder / ('images_' + 'x' * 30)
        folder.mkdir(parents=True)
        source = folder / 'صورة.png'
        try:
            Image.new('RGB', (40, 30)).save(source)
        except OSError as exc:
            self.skipTest(f'Host long-path support unavailable: {exc}')
        broken = self.root / 'broken.jpg'
        broken.write_bytes(b'broken')
        jobs = [Job(source, Path('صورة.png')), Job(broken, Path('broken.jpg'))]
        totals = run_batch(jobs, self.settings, Control(), lambda *_: None, lambda *_: None)
        self.assertEqual((totals['done'], totals['error']), (1, 1))

    def test_high_bit_depth_and_multiframe_safety(self):
        from dataclasses import replace
        source = self.root / 'depth.tiff'
        with Image.new('I;16', (80, 40), 50000) as image:
            image.save(source)
        job = Job(source, Path(source.name))
        settings = replace(self.settings, resize='Keep original')
        self.assertEqual(process(job, settings, Control(), lambda _: None)[0], 'done')
        with Image.open(settings.output / job.relative) as output:
            self.assertEqual(output.getpixel((0, 0)), 50000)
        frames = [Image.new('RGB', (20, 20), color) for color in ('red', 'blue')]
        try:
            frames[0].save(source, save_all=True, append_images=frames[1:])
        finally:
            for frame in frames:
                frame.close()
        original = source.read_bytes()
        self.assertEqual(process(job, replace(settings, in_place=True), Control(), lambda _: None)[0], 'error')
        self.assertEqual(source.read_bytes(), original)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows sharing semantics')
    def test_real_windows_file_lock_does_not_destroy_destination(self):
        import ctypes
        from dataclasses import replace
        destination = self.settings.output / self.job.relative
        destination.parent.mkdir()
        destination.write_bytes(b'Existing output must survive')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(destination), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            result = process(self.job, replace(self.settings, overwrite=True), Control(), lambda _: None)
            self.assertEqual(result[0], 'error')
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(destination.read_bytes(), b'Existing output must survive')
        self.assertFalse(list(destination.parent.glob('.os96-*')))

    def test_oversized_output_rejected_without_allocating_it(self):
        from dataclasses import replace
        result = process(self.job, replace(self.settings, width=100000, height=100000), Control(), lambda _: None)
        self.assertEqual(result[0], 'error')
        self.assertFalse((self.settings.output / self.job.relative).exists())

    def test_16_bit_color_png_rejected_instead_of_silently_truncated(self):
        import struct
        import zlib
        path = self.root / 'color16.png'
        def chunk(name, data):
            return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
        header = struct.pack('>IIBBBBB', 2, 1, 16, 2, 0, 0, 0)
        pixels = b'\x00' + struct.pack('>HHH', 10000, 20000, 30000) * 2
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))
        messages = []
        result = process(Job(path, Path(path.name)), self.settings, Control(), messages.append)
        self.assertEqual(result[0], 'error')
        self.assertIn('preserve channel precision', messages[-1])
        self.assertFalse((self.settings.output / path.name).exists())

    def test_16_bit_color_tiff_rejected_instead_of_silently_truncated(self):
        import struct
        path = self.root / 'color16.tiff'
        count = 10
        bits_offset = 8 + 2 + count * 12 + 4
        pixels_offset = bits_offset + 6
        tags = [(256,4,1,2), (257,4,1,1), (258,3,3,bits_offset), (259,3,1,1),
                (262,3,1,2), (273,4,1,pixels_offset), (277,3,1,3), (278,4,1,1),
                (279,4,1,12), (284,3,1,1)]
        data = b'II' + struct.pack('<HIH', 42, 8, count)
        data += b''.join(struct.pack('<HHII', *tag) for tag in tags) + struct.pack('<I', 0)
        data += struct.pack('<HHH', 16, 16, 16) + struct.pack('<HHH', 10000, 20000, 30000) * 2
        path.write_bytes(data)
        messages = []
        result = process(Job(path, Path(path.name)), self.settings, Control(), messages.append)
        self.assertEqual(result[0], 'error')
        self.assertIn('preserve channel precision', messages[-1])


if __name__ == '__main__':
    unittest.main()
