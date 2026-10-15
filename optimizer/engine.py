from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from PIL import Image, ImageOps

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp'}


@dataclass(frozen=True)
class Job:
    source: Path
    relative: Path


@dataclass(frozen=True)
class Settings:
    output: Path
    in_place: bool = False
    resize: str = 'Keep original'
    width: int = 1920
    height: int = 1080
    dimension_mode: str = 'Exact'
    dpi: int = 300
    print_width: float = 6.0
    print_height: float = 4.0
    print_unit: str = 'in'
    lossless: bool = True
    quality: int = 85
    png_level: int = 6
    metadata: bool = True
    color_profile: bool = True
    workers: int = 2
    overwrite: bool = False


def discover(paths: list[Path]) -> tuple[list[Job], list[str]]:
    jobs, errors, seen = [], [], set()
    roots = [p.resolve() for p in paths]
    folders = [p for p in roots if p.is_dir()]
    # A common parent keeps siblings and overlapping selections consistent.
    base = Path(os.path.commonpath([str(p.parent) for p in roots])) if roots else Path('.')
    if len(roots) == 1 and folders:
        base = roots[0]
    def add(p):
        if p.suffix.lower() not in EXTENSIONS or p.is_symlink():
            return
        key = os.path.normcase(str(p.resolve()))
        if key not in seen:
            seen.add(key)
            jobs.append(Job(p, p.relative_to(base)))
    for root in roots:
        if root.is_dir():
            def error(exc):
                errors.append(str(exc))
            for directory, _, files in os.walk(root, followlinks=False, onerror=error):
                for filename in sorted(files):
                    add(Path(directory) / filename)
        elif root.is_file():
            add(root)
        else:
            errors.append(f'Not found: {root}')
    return sorted(jobs, key=lambda j: str(j.source)), errors


class Control:
    def __init__(self):
        self.condition = threading.Condition()
        self.paused = False
        self.stopped = False

    def pause(self, value):
        with self.condition:
            self.paused = value
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def checkpoint(self):
        with self.condition:
            while self.paused and not self.stopped:
                self.condition.wait()
            return not self.stopped


def target_size(size, settings):
    w, h = size
    if settings.resize == 'By dimensions':
        if settings.dimension_mode == 'Exact':
            return settings.width, settings.height
        use_width = w >= h if settings.dimension_mode == 'Auto' else settings.dimension_mode == 'Width'
        ratio = settings.width / w if use_width else settings.height / h
    elif settings.resize == 'By resolution':
        divisor = 2.54 if settings.print_unit == 'cm' else 1
        return (max(1, round(settings.print_width / divisor * settings.dpi)),
                max(1, round(settings.print_height / divisor * settings.dpi)))
    else:
        return size
    return max(1, round(w * ratio)), max(1, round(h * ratio))


def copy_jpeg(source, destination, metadata, color_profile, orientation=1):
    """Filter JPEG headers without decoding/reencoding the compressed pixels."""
    with open(source, 'rb') as incoming, open(destination, 'wb') as outgoing:
        if incoming.read(2) != b'\xff\xd8':
            raise ValueError('Invalid JPEG header')
        outgoing.write(b'\xff\xd8')
        if not metadata and orientation != 1:
            exif = Image.Exif()
            exif[274] = orientation
            payload = exif.tobytes()
            outgoing.write(b'\xff\xe1' + (len(payload) + 2).to_bytes(2, 'big') + payload)
        while True:
            prefix = incoming.read(1)
            if prefix != b'\xff':
                raise ValueError('Invalid JPEG marker')
            marker = incoming.read(1)
            while marker == b'\xff':
                marker = incoming.read(1)
            if not marker:
                raise ValueError('Truncated JPEG header')
            code = marker[0]
            if code == 0xD9:
                outgoing.write(prefix + marker)
                break
            if code == 0x01 or 0xD0 <= code <= 0xD7:
                outgoing.write(prefix + marker)
                continue
            length_bytes = incoming.read(2)
            length = int.from_bytes(length_bytes, 'big')
            if len(length_bytes) != 2 or length < 2:
                raise ValueError('Invalid JPEG segment length')
            payload = incoming.read(length - 2)
            if len(payload) != length - 2:
                raise ValueError('Truncated JPEG segment')
            keep = True
            if code == 0xE2 and payload.startswith(b'ICC_PROFILE\x00'):
                keep = color_profile
            elif code == 0xE0 and payload.startswith(b'JFIF\x00'):
                keep = True  # Density and compatibility header.
            elif code == 0xEE and payload.startswith(b'Adobe'):
                keep = True  # Required for correct CMYK decoding.
            elif 0xE0 <= code <= 0xEF or code == 0xFE:
                keep = metadata
            if keep:
                outgoing.write(prefix + marker + length_bytes + payload)
            if code == 0xDA:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                break


def process(job: Job, settings: Settings, control: Control, emit):
    temporary = None
    try:
        if not control.checkpoint():
            return 'cancelled', 0, 0
        emit('Reading')
        destination = job.source if settings.in_place else settings.output / job.relative
        if not settings.in_place and destination.resolve() == job.source.resolve():
            raise ValueError('Select “Replace originals” to write to the source file.')
        if destination.exists() and not settings.in_place and not settings.overwrite:
            emit('Skipped · output exists')
            return 'skipped', 0, 0
        before = job.source.stat().st_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(job.source) as original:
            if getattr(original, 'n_frames', 1) > 1:
                raise ValueError('Animated or multipage image skipped to preserve all frames.')
            fmt = original.format
            # Avoid changing JPEG pixels when lossless mode is requested.
            copy_original = settings.lossless and settings.resize == 'Keep original' and fmt == 'JPEG'
            handle, name = tempfile.mkstemp(prefix='.os96-', suffix=job.source.suffix, dir=destination.parent)
            os.close(handle)
            temporary = Path(name)
            if copy_original:
                if settings.metadata and settings.color_profile:
                    shutil.copy2(job.source, temporary)
                else:
                    copy_jpeg(job.source, temporary, settings.metadata, settings.color_profile,
                              original.getexif().get(274, 1))
            else:
                image = ImageOps.exif_transpose(original)
                try:
                    size = target_size(image.size, settings)
                    if size[0] * size[1] > Image.MAX_IMAGE_PIXELS:
                        raise ValueError('Requested output exceeds the safe pixel limit. Reduce dimensions, print size, or DPI.')
                    if size != image.size:
                        emit('Resizing')
                        resized = image.resize(size, Image.Resampling.LANCZOS)
                        image.close()
                        image = resized
                    if not control.checkpoint():
                        emit('Cancelled')
                        return 'cancelled', 0, 0
                    emit('Encoding')
                    options = {}
                    if settings.color_profile and original.info.get('icc_profile'):
                        options['icc_profile'] = original.info['icc_profile']
                    elif not settings.color_profile:
                        image.info.pop('icc_profile', None)
                        options['icc_profile'] = b''
                    if not settings.metadata:
                        for key in ('exif', 'xmp', 'XML:com.adobe.xmp'):
                            image.info.pop(key, None)
                    if settings.metadata:
                        exif = original.getexif()
                        if fmt == 'TIFF':
                            # TIFF IFDs also contain source pixel layout and offsets.
                            # Never carry those structural tags into a new image.
                            descriptive = Image.Exif()
                            for tag in (269, 270, 271, 272, 282, 283, 296, 305, 306, 315, 33432):
                                if tag in exif:
                                    descriptive[tag] = exif[tag]
                            exif = descriptive
                        if exif:
                            exif.pop(274, None)
                            exif[40962], exif[40963] = image.size
                            options['exif'] = exif.tobytes()
                        if fmt == 'PNG':
                            from PIL.PngImagePlugin import PngInfo
                            info = PngInfo()
                            for key, value in original.info.items():
                                if isinstance(value, str):
                                    info.add_text(key, value)
                            options['pnginfo'] = info
                    if settings.resize == 'By resolution':
                        options['dpi'] = (settings.dpi, settings.dpi)
                        # WebP stores print density in EXIF rather than a DPI header.
                        exif = Image.Exif()
                        if options.get('exif'):
                            exif.load(options['exif'])
                        exif[282] = exif[283] = settings.dpi
                        exif[296] = 2  # Pixels per inch.
                        options['exif'] = exif.tobytes()
                    if fmt == 'JPEG':
                        options.update(quality=100 if settings.lossless else settings.quality, optimize=True, subsampling=0)
                    elif fmt == 'PNG':
                        options.update(compress_level=settings.png_level)
                    elif fmt == 'WEBP':
                        options.update(lossless=settings.lossless, quality=85 if settings.lossless else settings.quality, method=4)
                    elif fmt == 'TIFF':
                        options.update(compression='tiff_deflate')
                    image.save(temporary, format=fmt, **options)
                finally:
                    image.close()
        if not control.checkpoint():
            emit('Cancelled')
            return 'cancelled', 0, 0
        # Keep the smaller original when no resize/metadata removal was requested.
        if settings.resize == 'Keep original' and settings.metadata and settings.color_profile and temporary.stat().st_size >= before:
            shutil.copy2(job.source, temporary)
        after = temporary.stat().st_size
        if settings.in_place or settings.overwrite:
            os.replace(temporary, destination)
        else:
            # Exclusive creation protects files that appear after the initial check.
            os.link(temporary, destination)
            temporary.unlink()
        temporary = None
        emit('Done')
        return 'done', before, after
    except Exception as exc:
        emit(f'Error · {exc}')
        return 'error', 0, 0
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_batch(jobs, settings, control, status, progress):
    totals = dict(done=0, error=0, skipped=0, cancelled=0, before=0, after=0)
    iterator = iter(enumerate(jobs))
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        pending = {}
        def submit():
            if not control.checkpoint():
                return False
            try:
                index, job = next(iterator)
            except StopIteration:
                return False
            future = pool.submit(process, job, settings, control, lambda message: status(index, message))
            pending[future] = index
            return True
        for _ in range(settings.workers):
            if not submit():
                break
        completed = 0
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future)
                result, before, after = future.result()
                totals[result] += 1
                totals['before'] += before
                totals['after'] += after
                completed += 1
                progress(completed, totals.copy())
            while len(pending) < settings.workers and submit():
                pass
    return totals
