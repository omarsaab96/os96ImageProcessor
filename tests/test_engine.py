import tempfile
import unittest
import threading
from pathlib import Path
from PIL import Image, ImageCms, ImageOps
from optimizer.engine import Job, Settings, Control, discover, process, run_batch, target_size


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'input'
        self.source.mkdir()
        self.output = self.root / 'output'

    def tearDown(self):
        self.temp.cleanup()

    def make_image(self, relative='nested/image.png'):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (160, 80), (20, 100, 160)).save(path)
        return path

    def test_hierarchy_and_deduplication(self):
        path = self.make_image()
        jobs, errors = discover([self.source])
        self.assertFalse(errors)
        self.assertEqual(jobs[0].relative, Path('nested/image.png'))
        jobs, _ = discover([self.source, path])
        self.assertEqual(len(jobs), 1)

    def test_lossless_pixels_and_existing_output(self):
        path = self.make_image()
        job = Job(path, Path('nested/image.png'))
        settings = Settings(self.output)
        result = process(job, settings, Control(), lambda _: None)
        self.assertEqual(result[0], 'done')
        with Image.open(path) as a, Image.open(self.output / job.relative) as b:
            self.assertEqual(a.tobytes(), b.tobytes())
        self.assertEqual(process(job, settings, Control(), lambda _: None)[0], 'skipped')

    def test_resize_and_in_place(self):
        path = self.make_image()
        result = process(Job(path, Path('image.png')), Settings(self.output, in_place=True,
                         resize='By dimensions', dimension_mode='Width', width=40, height=40), Control(), lambda _: None)
        self.assertEqual(result[0], 'done')
        with Image.open(path) as image:
            self.assertEqual(image.size, (40, 20))
        self.assertFalse(list(path.parent.glob('.os96-*')))

    def test_error_does_not_stop_batch(self):
        good = self.make_image()
        bad = self.source / 'bad.png'
        bad.write_bytes(b'broken')
        jobs, _ = discover([self.source])
        result = run_batch(jobs, Settings(self.output), Control(), lambda *_: None, lambda *_: None)
        self.assertEqual((result['done'], result['error']), (1, 1))
        self.assertTrue(good.exists())

    def test_cancel_leaves_original(self):
        path = self.make_image()
        original = path.read_bytes()
        control = Control()
        def status(message):
            if message == 'Encoding':
                control.stop()
        result = process(Job(path, Path('image.png')), Settings(self.output, in_place=True,
                         resize='By dimensions', dimension_mode='Exact', width=20, height=20), control, status)
        self.assertEqual(result[0], 'cancelled')
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob('.os96-*')))

    def test_jpeg_lossless_is_byte_identical(self):
        path = self.make_image('photo.jpg')
        process(Job(path, Path('photo.jpg')), Settings(self.output), Control(), lambda _: None)
        self.assertEqual(path.read_bytes(), (self.output / 'photo.jpg').read_bytes())

    def test_pause_resume_and_stop_release_waiters(self):
        control = Control()
        control.pause(True)
        completed = threading.Event()
        thread = threading.Thread(target=lambda: (control.checkpoint(), completed.set()))
        thread.start()
        self.assertFalse(completed.wait(.05))
        control.pause(False)
        self.assertTrue(completed.wait(2))
        thread.join()
        control.pause(True)
        control.stop()
        self.assertFalse(control.checkpoint())

    def test_stopped_batch_does_not_write(self):
        self.make_image()
        jobs, _ = discover([self.source])
        control = Control()
        control.stop()
        totals = run_batch(jobs, Settings(self.output), control, lambda *_: None, lambda *_: None)
        self.assertEqual(totals['done'], 0)
        self.assertFalse(self.output.exists())

    def test_supported_formats_resize(self):
        for extension in ('jpg', 'webp', 'tiff', 'bmp', 'png'):
            with self.subTest(extension=extension):
                path = self.make_image('sample.' + extension)
                result = process(Job(path, Path(path.name)), Settings(self.output,
                                 resize='By dimensions', dimension_mode='Exact', width=32, height=24),
                                 Control(), lambda _: None)
                self.assertEqual(result[0], 'done')
                with Image.open(self.output / path.name) as image:
                    self.assertEqual(image.size, (32, 24))

    def test_dimension_options_and_enlargement(self):
        from dataclasses import replace
        settings = Settings(self.output, resize='By dimensions', dimension_mode='Width', width=80, height=30)
        self.assertEqual(target_size((160, 80), settings), (80, 40))
        self.assertEqual(target_size((160, 80), replace(settings, dimension_mode='Height')), (60, 30))
        self.assertEqual(target_size((160, 80), replace(settings, dimension_mode='Exact')), (80, 30))
        settings = replace(settings, dimension_mode='Auto')
        self.assertEqual(target_size((160, 80), settings), (80, 40))
        self.assertEqual(target_size((80, 160), settings), (15, 30))
        self.assertEqual(target_size((160, 160), settings), (80, 80))
        for option, expected in [('Width', (80, 40)), ('Height', (60, 30)), ('Exact', (80, 30)), ('Auto', (80, 40))]:
            self.assertEqual(target_size((16, 8), replace(settings, dimension_mode=option)), expected)

    def test_resolution_resamples_and_writes_density(self):
        from dataclasses import replace
        settings = Settings(self.output, resize='By resolution', dpi=200, print_width=2, print_height=1,
                            metadata=False)
        self.assertEqual(target_size((160, 80), settings), (400, 200))
        self.assertEqual(target_size((160, 80), replace(settings, dpi=600)), (1200, 600))
        self.assertEqual(target_size((160, 80), replace(settings, print_unit='cm',
                         print_width=5.08, print_height=2.54)), (400, 200))
        for extension in ('jpg', 'png', 'tiff', 'bmp', 'webp'):
            with self.subTest(extension=extension):
                path = self.make_image('density.' + extension)
                result = process(Job(path, Path(path.name)), settings, Control(), lambda _: None)
                self.assertEqual(result[0], 'done')
                with Image.open(self.output / path.name) as image:
                    self.assertEqual(image.size, (400, 200))
                    density = image.getexif().get(282) if extension == 'webp' else image.info['dpi'][0]
                    self.assertAlmostEqual(float(density), 200, delta=.1)

    def test_metadata_and_profiles_are_independent(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        for extension in ('jpg', 'png', 'webp', 'tiff'):
            source = self.source / ('tagged.' + extension)
            exif = Image.Exif()
            exif[315] = 'Test photographer'
            exif[274] = 6
            Image.new('RGB', (40, 20), 'navy').save(source, exif=exif, icc_profile=profile)
            for metadata in (True, False):
                for color_profile in (True, False):
                    with self.subTest(extension=extension, metadata=metadata, color_profile=color_profile):
                        relative = Path(f'{metadata}-{color_profile}.{extension}')
                        result = process(Job(source, relative), Settings(self.output,
                                         metadata=metadata, color_profile=color_profile), Control(), lambda _: None)
                        self.assertEqual(result[0], 'done')
                        with Image.open(self.output / relative) as output:
                            self.assertEqual(output.info.get('icc_profile'), profile if color_profile else None)
                            self.assertEqual(output.getexif().get(315), 'Test photographer' if metadata else None)
                            if extension == 'jpg':
                                with Image.open(source) as original:
                                    self.assertEqual(output.tobytes(), original.tobytes())
                                    self.assertEqual(ImageOps.exif_transpose(output).tobytes(),
                                                     ImageOps.exif_transpose(original).tobytes())


if __name__ == '__main__':
    unittest.main()
