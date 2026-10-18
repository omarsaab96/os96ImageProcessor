import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from optimizer.compression import quality_ok
from optimizer.engine import Job, Settings, Control, process
from optimizer.native import optimize_native, tool_path, pixel_equal


class CompressionProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_chroma_edges_still_fail_quality_gate(self):
        with Image.new('RGB', (256, 256), 'red') as original:
            draw = ImageDraw.Draw(original)
            for x in range(0, 256, 2):
                draw.line((x, 0, x, 255), fill='blue')
            path = self.root / 'subsampled.jpg'
            original.save(path, quality=100, subsampling=2)
            with Image.open(path) as decoded:
                self.assertFalse(quality_ok(original, decoded))

    def test_alpha_changes_cannot_pass_rgb_quality_gate(self):
        with Image.new('RGBA', (64, 64), (20, 100, 160, 0)) as a, Image.new('RGBA', (64, 64), (20, 100, 160, 255)) as b:
            self.assertFalse(quality_ok(a, b))

    def test_lossless_webp_retains_invisible_rgb_and_alpha(self):
        source = self.root / 'input.webp'
        with Image.new('RGBA', (40, 40), (200, 10, 70, 0)) as image:
            image.putpixel((10, 10), (10, 100, 200, 120))
            image.save(source, lossless=True, exact=True)
        output = self.root / 'output'
        for smart in (False, True):
            result = process(Job(source, Path(source.name)), Settings(output, smart=smart, overwrite=True), Control(), lambda _: None)
            self.assertEqual(result[0], 'done')
            with Image.open(source) as a, Image.open(output / source.name) as b:
                self.assertEqual(a.convert('RGBA').tobytes(), b.convert('RGBA').tobytes())

    def test_jpeg_lossless_optimization_reduces_without_reencoding(self):
        if tool_path('jpegtran') is None:
            self.skipTest('Bundled jpegtran unavailable')
        path = self.root / 'input.jpg'
        exif = Image.Exif()
        exif[315] = 'Test photographer'
        with Image.new('RGB', (512, 384), 'navy') as image:
            image.save(path, quality=95, optimize=False, exif=exif)
        original = path.read_bytes()
        optimize_native(path, 'JPEG', Control(), lambda _: None)
        self.assertLess(path.stat().st_size, len(original))
        from io import BytesIO
        with Image.open(BytesIO(original)) as a, Image.open(path) as b:
            self.assertTrue(pixel_equal(a, b))
            self.assertEqual(dict(a.getexif()), dict(b.getexif()))

    def test_native_timeout_keeps_existing_valid_image(self):
        path = self.root / 'input.png'
        Image.new('RGB', (20, 20), 'navy').save(path)
        original = path.read_bytes()
        with patch('optimizer.native.tool_path', return_value=Path('fake.exe')), patch('optimizer.native.subprocess.run', side_effect=subprocess.TimeoutExpired('fake', 120)):
            optimize_native(path, 'PNG', Control(), lambda _: None)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.os96-native-*')))

    def test_native_cannot_commit_pixel_damage(self):
        path = self.root / 'input.png'
        Image.new('RGB', (20, 20), 'navy').save(path, compress_level=0)
        original = path.read_bytes()
        def damage(arguments, **kwargs):
            Image.new('RGB', (20, 20), 'red').save(Path(arguments[arguments.index('--out') + 1]))
        with patch('optimizer.native.tool_path', return_value=Path('fake.exe')), patch('optimizer.native.subprocess.run', side_effect=damage):
            optimize_native(path, 'PNG', Control(), lambda _: None)
        self.assertEqual(path.read_bytes(), original)

    def test_native_cannot_strip_metadata(self):
        from PIL.PngImagePlugin import PngInfo
        path = self.root / 'input.png'
        info = PngInfo()
        info.add_text('Author', 'Must survive')
        Image.new('RGB', (20, 20), 'navy').save(path, compress_level=0, pnginfo=info)
        original = path.read_bytes()
        def strip(arguments, **kwargs):
            Image.new('RGB', (20, 20), 'navy').save(Path(arguments[arguments.index('--out') + 1]))
        with patch('optimizer.native.tool_path', return_value=Path('fake.exe')), patch('optimizer.native.subprocess.run', side_effect=strip):
            optimize_native(path, 'PNG', Control(), lambda _: None)
        self.assertEqual(path.read_bytes(), original)

    def test_already_quantized_jpeg_uses_fast_lossless_path(self):
        if tool_path('jpegtran') is None:
            self.skipTest('Bundled jpegtran unavailable')
        source = self.root / 'photo.jpg'
        with Image.new('RGB', (128, 96), 'navy') as image:
            image.save(source, quality=75)
        with patch('optimizer.engine.encode_smart', side_effect=AssertionError('Lossy search should not run')):
            result = process(Job(source, Path(source.name)), Settings(self.root / 'output', smart=True), Control(), lambda _: None)
        self.assertEqual(result[0], 'done')
        with Image.open(source) as a, Image.open(self.root / 'output' / source.name) as b:
            self.assertTrue(pixel_equal(a, b))
