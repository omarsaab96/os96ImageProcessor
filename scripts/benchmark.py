"""Reproducible synthetic throughput/quality baseline; optionally use a real corpus."""
import argparse
import ctypes
import hashlib
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageOps, __version__ as pillow_version
from optimizer.engine import Settings, Control, discover, run_batch
from optimizer.compression import quality_ok


def peak_memory():
    if sys.platform == 'win32':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong),
                *[(name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                  'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                  'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if ctypes.windll.psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return round(counters.PeakWorkingSetSize / 1048576, 1)
        return None
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1048576 if sys.platform == 'darwin' else 1024), 1)


def fixture(folder, count):
    for i in range(count):
        image = Image.new('RGB', (512, 384), (i % 256, 70, 160))
        draw = ImageDraw.Draw(image)
        for x in range(0, 512, 8):
            draw.rectangle((x, 0, x + 3, 383), fill=(x % 256, (i * 13) % 256, 100))
        draw.text((20, 20), 'OS96 compression benchmark: fine text 0123456789', fill='white')
        image.save(folder / f'{i:04}.jpg', quality=98, subsampling=0)
        image.close()
    with Image.effect_noise((2400, 1600), 35).convert('RGB') as photo:
        photo.save(folder / 'large-texture.jpg', quality=98, subsampling=0)
    with Image.new('RGBA', (1200, 800), (30, 100, 200, 120)) as alpha:
        alpha.save(folder / 'alpha.png')
        alpha.save(folder / 'alpha.webp', lossless=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--count', type=int, default=128)
    parser.add_argument('--report', type=Path, default=Path('validation/benchmark.json'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='os96-bench-') as temporary:
        folder = Path(temporary)
        source = args.corpus or folder / 'source'
        if not args.corpus:
            source.mkdir()
            fixture(source, args.count)
        jobs, errors = discover([source])
        originals = {job.source: hashlib.sha256(job.source.read_bytes()).hexdigest() for job in jobs}
        statuses = {}
        start = time.perf_counter()
        totals = run_batch(jobs, Settings(folder / 'output', smart=True, workers=2), Control(),
                           lambda i, message: statuses.update({i: message}), lambda *_: None)
        seconds = time.perf_counter() - start
        peak = peak_memory()
        quality = {}
        for job in jobs:
            target = folder / 'output' / job.relative
            if target.exists():
                with Image.open(job.source) as a, Image.open(target) as b:
                    with ImageOps.exif_transpose(a) as oriented:
                        quality[str(job.relative)] = quality_ok(oriented, b)
        report = dict(corpus='user supplied' if args.corpus else 'synthetic text, edges, noise, alpha; not a photographic quality benchmark',
            platform=platform.platform(), python=platform.python_version(), pillow=pillow_version,
            files=len(jobs), seconds=round(seconds, 3), images_per_second=round(len(jobs) / max(seconds, .001), 2),
            peak_working_set_mb=peak, totals=totals, errors=errors,
            originals_unchanged=all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in originals.items()),
            quality_checks_passed=sum(quality.values()), quality_checks_total=len(quality),
            quality_failures=[name for name, passed in quality.items() if not passed],
            statuses={str(i): message for i, message in statuses.items() if message != 'Done'})
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        if totals['error'] or not report['originals_unchanged']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
