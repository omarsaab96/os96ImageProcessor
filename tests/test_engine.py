import tempfile
import unittest
import threading
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageCms, ImageOps
from optimizer.engine import Job, Settings, Control, discover, process, run_batch, target_size, estimate_output, batch_worker_limit, open_photo
from optimizer.compression import quality_ok


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

    def test_mpf_thumbnail_is_processed_as_single_jpeg(self):
        from unittest.mock import patch
        path = self.source / 'camera.JPG'
        with Image.new('RGB', (160, 80), 'red') as primary, Image.new('RGB', (40, 20), 'blue') as preview:
            primary.save(path, format='MPO', save_all=True, append_images=[preview])
        opened = Image.open(path)
        opened.mpinfo[45058][0]['Attribute']['MPType'] = 'Baseline MP Primary Image'
        opened.mpinfo[45058][1]['Attribute']['MPType'] = 'Large Thumbnail (Full HD Equivalent)'
        with patch('optimizer.engine.Image.open', return_value=opened):
            with open_photo(path) as photo:
                self.assertEqual(photo.format, 'JPEG')
                self.assertEqual(photo.size, (160, 80))
                self.assertEqual(getattr(photo, 'n_frames', 1), 1)
                photo.load()

    def test_metadata_rewrite_removes_stale_mpf_offsets(self):
        from optimizer.engine import copy_jpeg
        path = self.source / 'camera.JPG'
        with Image.new('RGB', (160, 80), 'red') as primary, Image.new('RGB', (40, 20), 'blue') as preview:
            primary.save(path, format='MPO', save_all=True, append_images=[preview])
        destination = self.source / 'rewritten.jpg'
        copy_jpeg(path, destination, True, True, 1)
        with Image.open(destination) as photo:
            self.assertEqual(photo.format, 'JPEG')
            photo.load()
            self.assertEqual(photo.size, (160, 80))

    def test_real_mpo_sequence_is_still_rejected(self):
        path = self.source / 'stereo.JPG'
        with Image.new('RGB', (160, 80), 'red') as first, Image.new('RGB', (160, 80), 'blue') as second:
            first.save(path, format='MPO', save_all=True, append_images=[second])
        messages = []
        result = process(Job(path, Path(path.name)), Settings(self.output), Control(), messages.append)
        self.assertEqual(result[0], 'error')
        self.assertTrue(any('multipage' in message for message in messages))
        self.assertFalse((self.output / path.name).exists())

    def test_apple_hdr_gain_map_exports_standard_jpeg(self):
        path = self.source / 'iphone.jpeg'
        xmp = (b'<x xmlns:apdi="http://ns.apple.com/pixeldatainfo/1.0/">'
               b'<apdi:AuxiliaryImageType>urn:com:apple:photo:2020:aux:hdrgainmap'
               b'</apdi:AuxiliaryImageType></x>')
        with Image.new('RGB', (160, 80), 'red') as primary, Image.new('RGB', (80, 40), 'gray') as gain:
            gain.encoderinfo = {'xmp': xmp}
            primary.save(path, format='MPO', save_all=True, append_images=[gain])
        with open_photo(path) as photo:
            self.assertEqual(photo.format, 'JPEG')
            self.assertEqual(photo.size, (160, 80))
        messages = []
        result = process(Job(path, Path(path.name)),
                         Settings(self.output, smart=False, lossless=False), Control(), messages.append)
        self.assertEqual(result[0], 'done', messages)
        with Image.open(self.output / path.name) as photo:
            self.assertEqual(photo.format, 'JPEG')
            self.assertEqual(getattr(photo, 'n_frames', 1), 1)
            self.assertEqual(photo.size, (160, 80))

    def test_unidentified_auxiliary_is_still_multipage(self):
        for xmp in (b'<broken', b'<x>urn:com:apple:photo:2020:aux:hdrgainmap</x>',
                    b'<x xmlns:apdi="http://ns.apple.com/pixeldatainfo/1.0/" '
                    b'apdi:AuxiliaryImageType="other"/>'):
            with self.subTest(xmp=xmp):
                path = self.source / 'unknown.jpeg'
                with Image.new('RGB', (160, 80)) as primary, Image.new('RGB', (80, 40)) as auxiliary:
                    auxiliary.encoderinfo = {'xmp': xmp}
                    primary.save(path, format='MPO', save_all=True, append_images=[auxiliary])
                with open_photo(path) as photo:
                    self.assertEqual(photo.format, 'MPO')
                    self.assertEqual(photo.tell(), 0)
                    self.assertEqual(photo.n_frames, 2)

    def test_hierarchy_and_deduplication(self):
        path = self.make_image()
        jobs, errors = discover([self.source])
        self.assertFalse(errors)
        self.assertEqual(jobs[0].relative, Path('nested/image.png'))
        jobs, _ = discover([self.source, path])
        self.assertEqual(len(jobs), 1)

    def test_large_images_reduce_parallelism_without_decoding(self):
        from unittest.mock import patch, MagicMock
        opened = MagicMock()
        opened.__enter__.return_value.size = (9504, 6336)
        opened.__enter__.return_value.width = 9504
        opened.__enter__.return_value.height = 6336
        with patch('optimizer.engine.Image.open', return_value=opened):
            self.assertEqual(batch_worker_limit([Job(Path('large.jpg'), Path('large.jpg'))], Settings(self.output)), 1)
            self.assertEqual(batch_worker_limit([Job(Path('large.jpg'), Path('large.jpg'))], Settings(self.output, workers=8)), 8)
        small = self.make_image()
        self.assertEqual(batch_worker_limit([Job(small, Path(small.name))], Settings(self.output, workers=4)), 4)
        with patch('optimizer.engine.Image.open', side_effect=Image.DecompressionBombError('too large')):
            self.assertEqual(batch_worker_limit([Job(small, Path(small.name))], Settings(self.output)), 2)

    def test_explicit_eight_workers_can_run_eight_jobs_concurrently(self):
        from unittest.mock import patch
        barrier = threading.Barrier(8, timeout=5)
        jobs = [Job(Path(f'photo-{i}.jpg'), Path(f'photo-{i}.jpg')) for i in range(8)]
        def concurrent_process(*args):
            barrier.wait()
            return 'done', 100, 50
        with patch('optimizer.engine.process', side_effect=concurrent_process):
            totals = run_batch(jobs, Settings(self.output, workers=8), Control(),
                               lambda *_: None, lambda *_: None)
        self.assertEqual(totals['done'], 8)

    def test_lossless_pixels_and_existing_output(self):
        path = self.make_image()
        job = Job(path, Path('nested/image.png'))
        settings = Settings(self.output, smart=False)
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

    def test_jpeg_lossless_preserves_decoded_pixels(self):
        path = self.make_image('photo.jpg')
        process(Job(path, Path('photo.jpg')), Settings(self.output, smart=False), Control(), lambda _: None)
        with Image.open(path) as source, Image.open(self.output / 'photo.jpg') as output:
            self.assertEqual(source.tobytes(), output.tobytes())
        self.assertLessEqual((self.output / 'photo.jpg').stat().st_size, path.stat().st_size)

    def test_smart_jpeg_compresses_with_and_without_resize(self):
        from dataclasses import replace
        path = self.source / 'gradient.jpg'
        with Image.new('RGB', (256, 192)) as image:
            image.putdata([(x, y, (x + y) // 2) for y in range(192) for x in range(256)])
            image.save(path, quality=100, subsampling=0)
        original = path.read_bytes()
        for resize in ('Keep original', 'By dimensions'):
            with self.subTest(resize=resize):
                settings = Settings(self.output, smart=True, resize=resize,
                                    width=128, height=96, overwrite=True)
                job = Job(path, Path('smart.jpg'))
                self.assertEqual(process(job, settings, Control(), lambda _: None)[0], 'done')
                with Image.open(path) as source:
                    reference = source.resize(target_size(source.size, settings), Image.Resampling.LANCZOS)
                    with reference, Image.open(self.output / 'smart.jpg') as result:
                        self.assertTrue(quality_ok(reference, result))
                manual = replace(settings, smart=False)
                self.assertEqual(process(Job(path, Path('maximum.jpg')), manual,
                                         Control(), lambda _: None)[0], 'done')
                self.assertLess((self.output / 'smart.jpg').stat().st_size,
                                (self.output / 'maximum.jpg').stat().st_size)
        self.assertEqual(path.read_bytes(), original)

    def test_quality_check_detects_local_damage(self):
        with Image.new('RGB', (512, 512), 'gray') as reference:
            changed = reference.copy()
            with changed:
                changed.paste('white', (0, 0, 16, 16))
                self.assertFalse(quality_ok(reference, changed))
                self.assertTrue(quality_ok(reference, reference))

    def test_resize_only_bypasses_compression_search_and_native_optimizer(self):
        from unittest.mock import patch
        for extension in ('jpg', 'png', 'webp'):
            source = self.make_image('resize-only.' + extension)
            settings = Settings(self.output, compress=False, smart=True, lossless=False,
                                quality=1, resize='By dimensions', width=64, height=32)
            with patch('optimizer.engine.encode_smart') as smart, patch('optimizer.engine.optimize_native') as native:
                result = process(Job(source, Path(source.name)), settings, Control(), lambda _: None)
                self.assertEqual(result[0], 'done')
                smart.assert_not_called()
                native.assert_not_called()
            with Image.open(self.output / source.name) as output:
                self.assertEqual(output.size, (64, 32))
                if extension == 'jpg':
                    self.assertTrue(all(value == 1 for value in output.quantization[0]))

    def test_no_steps_preserves_original_bytes(self):
        for extension in ('jpg', 'png', 'webp'):
            source = self.make_image('copy.' + extension)
            settings = Settings(self.output, compress=False)
            self.assertEqual(process(Job(source, Path(source.name)), settings, Control(), lambda _: None)[0], 'done')
            self.assertEqual(source.read_bytes(), (self.output / source.name).read_bytes())

    def test_jpeg_estimate_uses_native_texture_and_tracks_output(self):
        import random
        from PIL import ImageFilter
        source = self.source / 'texture.jpg'
        with Image.frombytes('L', (2000, 1500), random.Random(96).randbytes(3_000_000)) as noise:
            with noise.filter(ImageFilter.GaussianBlur(1.2)).convert('RGB') as image:
                image.save(source, quality=85, subsampling=0)
        settings = Settings(self.output)
        job = Job(source, Path(source.name))
        estimate = estimate_output(job, settings, Control(), self.root / 'estimate.jpg')
        result = process(job, settings, Control(), lambda _: None)
        self.assertEqual(result[0], 'done')
        self.assertLess(abs(estimate - result[2]) / result[2], .25)

    def test_smart_estimate_encodes_only_bounded_preview(self):
        from unittest.mock import patch
        from optimizer.compression import encode_smart
        path = self.source / 'large.jpg'
        with Image.new('RGB', (3000, 2000), 'navy') as image:
            image.save(path)
        original = path.read_bytes()
        sizes = []
        def record(image, *args):
            sizes.append(image.size)
            return encode_smart(image, *args)
        with patch('optimizer.engine.encode_smart', side_effect=record):
            size = estimate_output(Job(path, Path(path.name)), Settings(self.output, smart=True),
                                   Control(), self.root / 'preview')
        self.assertGreater(size, 0)
        self.assertEqual(len(sizes), 1)
        self.assertLessEqual(max(sizes[0]), 768)
        self.assertEqual(path.read_bytes(), original)

    def test_web_removes_metadata_preserves_profile_orientation_and_alpha(self):
        from PIL.PngImagePlugin import PngInfo
        path = self.source / 'web.png'
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        metadata = PngInfo()
        metadata.add_text('Description', 'remove this')
        exif = Image.Exif()
        exif[274] = 6
        with Image.new('RGBA', (40, 20), (10, 90, 150, 120)) as image:
            image.save(path, pnginfo=metadata, icc_profile=profile, exif=exif)
        original = path.read_bytes()
        self.assertEqual(process(Job(path, Path(path.name)), Settings(self.output, web=True),
                                 Control(), lambda _: None)[0], 'done')
        with Image.open(self.output / path.name) as result:
            self.assertEqual(result.size, (20, 40))
            self.assertEqual(result.convert('RGBA').getpixel((0, 0)), (10, 90, 150, 120))
            self.assertNotIn('Description', result.info)
            self.assertFalse(result.getexif())
            self.assertIn('sRGB', ImageCms.getProfileDescription(
                ImageCms.ImageCmsProfile(BytesIO(result.info['icc_profile']))))
        self.assertEqual(path.read_bytes(), original)

    def test_web_preserves_palette_transparency(self):
        path = self.source / 'palette.png'
        with Image.new('P', (20, 20), 0) as image:
            image.putpalette([255, 0, 0] * 256)
            image.save(path, transparency=0)
        self.assertEqual(process(Job(path, Path(path.name)), Settings(self.output, web=True),
                                 Control(), lambda _: None)[0], 'done')
        with Image.open(self.output / path.name) as result:
            self.assertEqual(result.convert('RGBA').getpixel((0, 0)), (255, 0, 0, 0))

    def test_web_jpeg_strips_exif_even_when_keep_metadata_is_requested(self):
        path = self.source / 'web.jpg'
        exif = Image.Exif()
        exif[315] = 'Private name'
        with Image.new('RGB', (40, 20), 'navy') as image:
            image.save(path, exif=exif)
        self.assertEqual(process(Job(path, Path(path.name)), Settings(self.output, web=True),
                                 Control(), lambda _: None)[0], 'done')
        with Image.open(self.output / path.name) as result:
            self.assertFalse(result.getexif())
            self.assertEqual(result.size, (40, 20))

    def test_web_respects_manual_compression_selection(self):
        from unittest.mock import patch
        path = self.make_image('manual.jpg')
        settings = Settings(self.output, web=True, smart=False, lossless=False, quality=82)
        with patch('optimizer.engine.encode_smart') as automatic:
            self.assertEqual(process(Job(path, Path(path.name)), settings, Control(), lambda _: None)[0], 'done')
            automatic.assert_not_called()
        with Image.open(self.output / path.name) as result:
            self.assertEqual(result.size, (160, 80))

    def test_web_smaller_only_skips_larger_candidate_without_color_fallback(self):
        from unittest.mock import patch
        path = self.source / 'small.jpg'
        exif = Image.Exif()
        exif[315] = 'Private name'
        with Image.effect_noise((600, 400), 20).convert('RGB') as image:
            image.save(path, quality=65, exif=exif)
        original = path.read_bytes()
        settings = Settings(self.output, web=True, smart=True, only_smaller=True)
        # Oversized web output must be skipped instead of bypassing conversion.
        def oversized(image, destination, *args):
            image.save(destination, format='JPEG', quality=100, subsampling=0)
            return True
        with patch('optimizer.engine.encode_smart', side_effect=oversized):
            estimate = estimate_output(Job(path, Path(path.name)), settings,
                                       Control(), self.root / 'sample')
            self.assertLessEqual(estimate, len(original))
            self.assertEqual(process(Job(path, Path(path.name)), settings,
                                     Control(), lambda _: None)[0], 'skipped')
        self.assertFalse((self.output / path.name).exists())
        self.assertEqual(path.read_bytes(), original)

    def test_web_invalid_profile_does_not_replace_source(self):
        path = self.source / 'bad-profile.png'
        with Image.new('RGB', (40, 20), 'red') as image:
            image.save(path, icc_profile=b'invalid profile')
        original = path.read_bytes()
        messages = []
        self.assertEqual(process(Job(path, Path(path.name)), Settings(self.output, web=True, in_place=True),
                                 Control(), messages.append)[0], 'error')
        self.assertIn('Cannot convert embedded color profile', messages[-1])
        self.assertEqual(path.read_bytes(), original)

    def test_smart_cancel_during_search_preserves_source(self):
        path = self.make_image('photo.jpg')
        original = path.read_bytes()
        control = Control()
        def status(message):
            if message.startswith('Optimizing'):
                control.stop()
        settings = Settings(self.output, smart=True, in_place=True)
        self.assertEqual(process(Job(path, Path(path.name)), settings, control, status)[0], 'cancelled')
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob('.os96-*')))

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
                with Image.effect_noise((800, 400), 30).convert('RGB') as source:
                    source.save(path)
                result = process(Job(path, Path(path.name)), settings, Control(), lambda _: None)
                self.assertEqual(result[0], 'done')
                with Image.open(self.output / path.name) as image:
                    self.assertEqual(image.size, (400, 200))
                    density = image.getexif().get(282) if extension == 'webp' else image.info['dpi'][0]
                    self.assertAlmostEqual(float(density), 200, delta=.1)

    def test_larger_output_is_skipped_without_replacing_source(self):
        path = self.make_image('tiny.png')
        original = path.read_bytes()
        messages = []
        settings = Settings(self.output, smart=False, in_place=True, resize='By dimensions',
                            width=1000, height=1000, only_smaller=True)
        self.assertEqual(process(Job(path, Path(path.name)), settings, Control(), messages.append)[0], 'skipped')
        self.assertEqual(messages[-1], 'Skipped · output would be larger')
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob('.os96-*')))

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
                                         smart=False, metadata=metadata, color_profile=color_profile), Control(), lambda _: None)
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
