"""Capture application-owned screens for visual release verification."""
import os
import sys
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from optimizer.app import create_application, Window, image_info
from optimizer.engine import Job, Settings
from optimizer.workflow import PreviewWorker


def main():
    app = create_application()
    if os.name == 'nt':
        QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts/segoeui.ttf'))
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else 'validation/screens')
    destination.mkdir(parents=True, exist_ok=True)
    window = Window()
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / 'sample.png'
        image = Image.new('RGB', (1000, 700), '#24488c')
        draw = ImageDraw.Draw(image)
        draw.ellipse((120, 100, 620, 600), fill='#f7b34b')
        draw.line((0, 700, 1000, 0), fill='white', width=4)
        image.save(source)
        image.close()
        job = Job(source, Path(source.name))
        window.scanned([job], [], [image_info(source)])
        window.show()
        for index, title in enumerate(('resize', 'optimize', 'destination')):
            window.options_tabs.setCurrentIndex(index)
            app.processEvents()
            window.grab().save(str(destination / f'{title}.png'))
        window.capture_batch(Settings(Path(temporary) / 'output'))
        window.table.item(0, 1).setText('Error · Example: output folder is read-only')
        window.finish_report({'done': 0, 'error': 1, 'before': 0, 'after': 0})
        def capture_modal(name):
            modal = app.activeModalWidget()
            if modal:
                modal.grab().save(str(destination / f'{name}.png'))
                modal.reject()
        QTimer.singleShot(100, lambda: capture_modal('report'))
        window.show_report()
        results = []
        worker = PreviewWorker(job, Settings(Path(temporary) / 'output'))
        worker.result.connect(lambda *args: results.append(args))
        worker.run()
        assert results and results[0][0] is not None
        QTimer.singleShot(100, lambda: capture_modal('comparison'))
        window.show_comparison(*results[0])
        window.close()


if __name__ == '__main__':
    main()
