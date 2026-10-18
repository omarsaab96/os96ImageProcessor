"""Run a substantial queue, pause/resume, stop, and preserve all source hashes."""
import hashlib
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from optimizer.engine import Settings, Job, Control, run_batch


def main():
    with tempfile.TemporaryDirectory(prefix='os96-stress-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        jobs = []
        for index in range(1000):
            path = source / f'image-{index:04}.png'
            with Image.new('RGBA', (96, 64), (index % 256, 100, 160, index % 255)) as image:
                image.save(path, compress_level=1)
            jobs.append(Job(path, Path(path.name)))
        hashes = {job.source: hashlib.sha256(job.source.read_bytes()).hexdigest() for job in jobs}
        control = Control()
        paused = []
        def progress(count, totals):
            if count == 10:
                control.pause(True)
                paused.append(True)
                threading.Timer(.1, lambda: control.pause(False)).start()
        start = time.perf_counter()
        totals = run_batch(jobs, Settings(root / 'output', smart=True, workers=2), control, lambda *_: None, progress)
        seconds = time.perf_counter() - start
        stop = Control()
        stopped = run_batch(jobs[:50], Settings(root / 'stopped-output', smart=True, workers=2), stop,
            lambda *_: None, lambda count, totals: stop.stop() if count >= 5 else None)
        unchanged = all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in hashes.items())
        temporary_files = [str(path) for path in root.rglob('.os96-*')]
        report = dict(passed=totals['done'] == 1000 and totals['error'] == 0 and unchanged and not temporary_files and stopped['done'] < 50,
            python=sys.version,
            images=1000, seconds=round(seconds, 3), workers=2, totals=totals,
            pause_resume_exercised=bool(paused), stopped_batch=stopped, source_hashes_unchanged=unchanged, temporary_files=temporary_files)
        (ROOT / 'validation/stress-release.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        if not report['passed']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
