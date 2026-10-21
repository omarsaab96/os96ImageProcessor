"""Noninteractive test of the actual frozen application and bundled Qt plugins."""
import json
import os
import tempfile
import traceback
import platform
from pathlib import Path


def run(report_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    report = {'passed': False}
    try:
        from PIL import Image
        from .app import create_application, Window, image_info
        from .engine import Job, Settings, Control, process
        from .workflow import PreviewWorker
        from . import __version__
        from .native import tool_path, pixel_equal, optimize_native
        from .compression import quality_ok
        app = create_application()
        if os.name == 'nt' and os.environ['QT_QPA_PLATFORM'] == 'offscreen':
            from PySide6.QtGui import QFontDatabase
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'))
        window = Window()
        checks = ['Qt window and plugin startup', 'resize encode/decode', 'thumbnail', 'full-resolution comparison']
        with tempfile.TemporaryDirectory(prefix='os96-selftest-') as temporary:
            root = Path(temporary)
            source = root / 'input.png'
            Image.new('RGBA', (160, 80), (20, 100, 160, 120)).save(source)
            job = Job(source, Path(source.name))
            settings = Settings(root / 'output', resize='By dimensions', width=80, height=40)
            status = []
            result = process(job, settings, Control(), status.append)
            assert result[0] == 'done', status
            with Image.open(settings.output / job.relative) as output:
                assert output.size == (80, 40)
            window.scanned([job], [], [image_info(source)])
            comparison = []
            worker = PreviewWorker(job, settings)
            worker.result.connect(lambda *values: comparison.append(values))
            worker.run()
            assert comparison and comparison[0][1].width() == 80
            # Exercise bundled codecs and the native helper processes as shipped.
            for extension, mode in (('jpg', 'RGB'), ('png', 'RGBA'), ('webp', 'RGBA'), ('tiff', 'RGB'), ('bmp', 'RGB')):
                image_path = root / ('صورة-é.' + extension)
                with Image.new(mode, (96, 64), (20, 100, 160, 120) if mode == 'RGBA' else (20, 100, 160)) as image:
                    image.save(image_path, **({'lossless': True, 'exact': True} if extension == 'webp' else {}))
                job = Job(image_path, Path(image_path.name))
                status = []
                result = process(job, Settings(root / 'codec-output', smart=True), Control(), status.append)
                assert result[0] == 'done', status
                with Image.open(root / 'codec-output' / job.relative) as decoded:
                    assert decoded.size == (96, 64)
                    if extension == 'jpg':
                        with Image.open(image_path) as reference:
                            assert quality_ok(reference, decoded, automatic=True)
                checks.append(extension + ' codec and Unicode path')
            for name in ('jpegtran', 'oxipng'):
                assert tool_path(name) is not None, name + ' bundled hash verification failed'
            checks.append('native helper integrity')
            native_path = root / 'entropy.jpg'
            with Image.new('RGB', (512, 384), 'navy') as image:
                image.save(native_path, optimize=False)
            job = Job(native_path, Path(native_path.name))
            result = process(job, Settings(root / 'native-output', smart=False), Control(), lambda _: None)
            assert result[0] == 'done'
            native_output = root / 'native-output' / job.relative
            assert native_output.stat().st_size < native_path.stat().st_size
            with Image.open(native_path) as a, Image.open(native_output) as b:
                assert pixel_equal(a, b)
            checks.append('native JPEG helper executes and preserves pixels')
            native_png = root / 'native-alpha.png'
            with Image.new('RGBA', (128, 96), (20, 100, 160, 120)) as image:
                image.save(native_png, compress_level=0)
            original_png = native_png.read_bytes()
            optimize_native(native_png, 'PNG', Control(), lambda _: None)
            assert native_png.stat().st_size < len(original_png)
            from io import BytesIO
            with Image.open(BytesIO(original_png)) as a, Image.open(native_png) as b:
                assert pixel_equal(a, b)
            checks.append('native PNG helper executes and preserves alpha')
            bad = root / 'damaged.png'
            bad.write_bytes(b'broken input')
            assert process(Job(bad, Path(bad.name)), Settings(root / 'bad-output'), Control(), lambda _: None)[0] == 'error'
            assert not (root / 'bad-output' / bad.name).exists()
            checks.append('damaged input leaves no output')
            window.show()
            app.processEvents()
            window.grab().save(str(Path(report_path).with_suffix('.png')))
            window.close()
        report.update(passed=True, version=__version__, platform=platform.platform(), checks=checks)
    except Exception:
        report['error'] = traceback.format_exc()
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1
