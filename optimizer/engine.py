from __future__ import annotations

import os
import shutil
import tempfile
import threading
from io import BytesIO
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from xml.etree import ElementTree

from PIL import Image, ImageOps, ImageCms
from .compression import encode_smart, jpeg_detail_sample
from .native import optimize_native

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
    workers: int = 0  # Automatic; positive values are explicit concurrency.
    overwrite: bool = False
    smart: bool = True
    web: bool = False
    only_smaller: bool = False
    compress: bool = True


def web_colors(image):
    """Convert tagged colors before stripping metadata; never just relabel them."""
    profile = image.info.get('icc_profile')
    if profile:
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
        prepared = image.convert('RGBA') if image.mode == 'P' else image
        try:
            converted = ImageCms.profileToProfile(
                prepared, ImageCms.ImageCmsProfile(BytesIO(profile)), srgb,
                outputMode='RGBA' if 'A' in prepared.getbands() else 'RGB')
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            raise ValueError('Cannot convert embedded color profile to sRGB; web export skipped to protect colors.') from exc
        finally:
            if prepared is not image:
                prepared.close()
        converted.info.clear()
        converted.info['icc_profile'] = srgb.tobytes()
        return converted
    if image.mode == 'CMYK':
        raise ValueError('CMYK web export requires an embedded color profile for accurate conversion.')
    converted = image.copy()
    # Untagged RGB is assumed to be sRGB; preserve palette and high bit depth.
    converted.info.clear()
    if 'transparency' in image.info:
        converted.info['transparency'] = image.info['transparency']
    return converted


@contextmanager
def open_photo(path):
    """Open MPF previews/Apple HDR auxiliaries as a standard single JPEG."""
    original = Image.open(path)
    try:
        entries = getattr(original, 'mpinfo', {}).get(45058, [])
        if (original.format == 'MPO' and len(entries) == original.n_frames
                and len(entries) > 1
                and entries[0]['Attribute']['MPType'] == 'Baseline MP Primary Image'
                and _single_photo_mpf(original, entries)):
            from PIL.JpegImagePlugin import JpegImageFile
            original.close()
            original = JpegImageFile(path)
        yield original
    finally:
        original.close()


def _single_photo_mpf(original, entries):
    """Accept only explicitly identified auxiliaries; unknown MPOs stay protected."""
    try:
        for index, entry in enumerate(entries[1:], 1):
            kind = entry['Attribute']['MPType']
            if kind in ('Large Thumbnail (VGA Equivalent)',
                        'Large Thumbnail (Full HD Equivalent)'):
                continue
            if kind != 'Undefined':
                return False
            original.seek(index)
            try:
                xmp = ElementTree.fromstring(original.info.get('xmp', b''))
            except ElementTree.ParseError:
                return False
            tag = '{http://ns.apple.com/pixeldatainfo/1.0/}AuxiliaryImageType'
            expected = 'urn:com:apple:photo:2020:aux:hdrgainmap'
            if not (any(node.text == expected for node in xmp.iter(tag))
                    or any(node.get(tag) == expected for node in xmp.iter())):
                return False
        return True
    finally:
        original.seek(0)


def estimate_output(job, settings, control, destination):
    """Estimate from a bounded preview; never run full-resolution trial encoding."""
    if not settings.compress:
        settings = replace(settings, smart=False, lossless=True)
    with open_photo(job.source) as original:
        if getattr(original, 'n_frames', 1) > 1:
            return None
        fmt = original.format
        reusable = reusable_jpeg(original, settings)
        stored = original.size
        oriented = stored[::-1] if original.getexif().get(274) in (5, 6, 7, 8) else stored
        target = target_size(oriented, settings)
        if target[0] * target[1] > Image.MAX_IMAGE_PIXELS:
            return None
        # JPEG draft decoding avoids decoding a 60 MP source just for a preview.
        native_detail = fmt == 'JPEG' and settings.resize == 'Keep original'
        if not native_detail:
            original.draft(original.mode, (768, 768))
        with (original if original.getexif().get(274, 1) == 1 else ImageOps.exif_transpose(original)) as image:
            scale = min(1.0, 768 / max(target))
            sample_size = tuple(max(1, round(value * scale)) for value in target)
            with (jpeg_detail_sample(image) if native_detail else
                  image.resize(sample_size, Image.Resampling.LANCZOS)) as sample:
                sample_size = sample.size
                prepared = web_colors(sample) if settings.web else sample.copy()
                with prepared:
                    options = {}
                    if settings.color_profile or settings.web:
                        profile = prepared.info.get('icc_profile')
                        if profile:
                            options['icc_profile'] = profile
                    metadata_bytes = 0
                    if settings.metadata and not settings.web:
                        exif = original.getexif()
                        metadata_bytes += len(exif.tobytes()) if exif else 0
                        metadata_bytes += sum(len(k.encode()) + len(v.encode())
                                              for k, v in original.info.items() if isinstance(v, str))
                    if fmt == 'JPEG':
                        options.update(quality=100 if settings.lossless else settings.quality,
                                       optimize=settings.compress, subsampling=0)
                    elif fmt == 'PNG':
                        options['compress_level'] = settings.png_level if settings.compress else 1
                    elif fmt == 'WEBP':
                        options.update(lossless=settings.lossless, quality=settings.quality, method=4 if settings.compress else 0)
                    elif fmt == 'TIFF':
                        options['compression'] = 'tiff_deflate'
                    if not control.checkpoint():
                        return None
                    if settings.smart:
                        if not encode_smart(prepared, destination, fmt, options, control, lambda _: None):
                            return None
                    else:
                        prepared.save(destination, format=fmt, **options)
                    # Profiles are fixed overhead and should not scale with pixels.
                    fixed = len(options.get('icc_profile', b''))
                    area_ratio = target[0] * target[1] / (sample_size[0] * sample_size[1])
                    estimate = round(max(0, destination.stat().st_size - fixed) * area_ratio) + fixed + metadata_bytes
                    if reusable:
                        copy_jpeg(job.source, destination, settings.metadata and not settings.web,
                                  settings.color_profile or settings.web, original.getexif().get(274, 1))
                        estimate = min(estimate, destination.stat().st_size)
                    if settings.resize == 'Keep original' and settings.metadata and settings.color_profile and not settings.web:
                        estimate = min(estimate, job.source.stat().st_size)
                    return min(estimate, job.source.stat().st_size) if settings.only_smaller else estimate


def reusable_jpeg(image, settings):
    """A metadata-only JPEG is a size fallback, retaining the source color profile."""
    return image.format == 'JPEG' and settings.resize == 'Keep original' and not settings.web


def check_precision(image):
    """Reject color depths that Pillow decodes to eight bits per channel."""
    if image.format == 'TIFF' and image.mode not in ('I', 'I;16', 'I;16B', 'I;16L', 'F'):
        bits = image.tag_v2.get(258, (8,))
        bits = (bits,) if isinstance(bits, int) else bits
        if any(value > 8 for value in bits):
            raise ValueError('High-bit-depth color TIFF is unsupported by this encoder; skipped to preserve channel precision.')
    if image.format == 'PNG' and image.mode in ('RGB', 'RGBA'):
        if any('16' in str(tile[3]) for tile in image.tile):
            raise ValueError('16-bit color PNG is unsupported by this encoder; skipped to preserve channel precision.')


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
            elif code == 0xE2 and payload.startswith(b'MPF\x00'):
                keep = False  # Rewritten headers invalidate MPF preview offsets.
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
        if not settings.compress:
            settings = replace(settings, smart=False, lossless=True)
        if settings.web:
            settings = replace(settings, metadata=False, color_profile=True)
        if not control.checkpoint():
            return 'cancelled', 0, 0
        emit('Reading')
        destination = job.source if settings.in_place else settings.output / job.relative
        if not settings.in_place and not destination.resolve().is_relative_to(settings.output.resolve()):
            raise ValueError('Output path must stay inside the destination folder.')
        if not settings.in_place and destination.resolve() == job.source.resolve():
            raise ValueError('Select “Replace originals” to write to the source file.')
        if destination.exists() and not settings.in_place and not settings.overwrite:
            emit('Skipped · output exists')
            return 'skipped', 0, 0
        before = job.source.stat().st_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open_photo(job.source) as original:
            check_precision(original)
            if getattr(original, 'n_frames', 1) > 1:
                raise ValueError('Animated or multipage image skipped to preserve all frames.')
            fmt = original.format
            reusable = reusable_jpeg(original, settings)
            # Avoid changing JPEG pixels when lossless mode is requested.
            needs_color_conversion = settings.web and bool(original.info.get('icc_profile'))
            copy_original = ((not settings.compress and settings.resize == 'Keep original'
                              and settings.metadata and settings.color_profile and not settings.web)
                             or (settings.lossless and not settings.smart and reusable and not needs_color_conversion))
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
                image = original if original.getexif().get(274, 1) == 1 else ImageOps.exif_transpose(original)
                try:
                    if settings.web:
                        converted = web_colors(image)
                        if image is not original:
                            image.close()
                        image = converted
                    size = target_size(image.size, settings)
                    if size[0] * size[1] > Image.MAX_IMAGE_PIXELS:
                        raise ValueError('Requested output exceeds the safe pixel limit. Reduce dimensions, print size, or DPI.')
                    if size != image.size:
                        emit('Resizing')
                        resized = image.resize(size, Image.Resampling.LANCZOS)
                        if image is not original:
                            image.close()
                        image = resized
                    if not control.checkpoint():
                        emit('Cancelled')
                        return 'cancelled', 0, 0
                    emit('Encoding')
                    options = {}
                    profile = image.info.get('icc_profile') if settings.web else original.info.get('icc_profile')
                    if settings.color_profile and profile:
                        options['icc_profile'] = profile
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
                        options.update(quality=100 if settings.lossless else settings.quality, optimize=settings.compress, subsampling=0)
                    elif fmt == 'PNG':
                        options.update(compress_level=settings.png_level if settings.compress else 1)
                    elif fmt == 'WEBP':
                        options.update(lossless=settings.lossless, quality=85 if settings.lossless else settings.quality, method=4 if settings.compress else 0, exact=True)
                    elif fmt == 'TIFF':
                        options.update(compression='tiff_deflate')
                    if settings.smart:
                        if not encode_smart(image, temporary, fmt, options, control, emit):
                            return 'cancelled', 0, 0
                    else:
                        image.save(temporary, format=fmt, **options)
                finally:
                    if image is not original:
                        image.close()
            if reusable and not copy_original:
                # Metadata-only export is a valid, pixel-preserving candidate.
                # Do not enlarge an existing JPEG just to reencode its pixels.
                handle, baseline_name = tempfile.mkstemp(prefix='.os96-', suffix=job.source.suffix, dir=destination.parent)
                os.close(handle)
                baseline = Path(baseline_name)
                try:
                    copy_jpeg(job.source, baseline, settings.metadata, settings.color_profile,
                              original.getexif().get(274, 1))
                    if baseline.stat().st_size < temporary.stat().st_size:
                        os.replace(baseline, temporary)
                finally:
                    baseline.unlink(missing_ok=True)
        if not control.checkpoint():
            emit('Cancelled')
            return 'cancelled', 0, 0
        # Keep the smaller original when no resize/metadata removal was requested.
        if settings.resize == 'Keep original' and settings.metadata and settings.color_profile and not settings.web and temporary.stat().st_size >= before:
            shutil.copy2(job.source, temporary)
        if settings.compress and ((fmt == 'JPEG' and not settings.smart) or (fmt == 'PNG' and settings.smart)):
            optimize_native(temporary, fmt, control, emit)
        if not control.checkpoint():
            emit('Cancelled')
            return 'cancelled', 0, 0
        after = temporary.stat().st_size
        if settings.only_smaller and after > before:
            emit('Skipped · output would be larger')
            return 'skipped', 0, 0
        # Never replace an original with an unreadable encoder result.
        with Image.open(temporary) as verification:
            verification.load()
        if settings.in_place or settings.overwrite:
            os.replace(temporary, destination)
        else:
            # Exclusive creation protects files that appear after the initial check.
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise
            except OSError:
                # FAT/exFAT and some network volumes do not support hard links.
                # Exclusive creation still protects pre-existing files.
                created = False
                try:
                    with open(destination, 'xb') as outgoing, open(temporary, 'rb') as incoming:
                        created = True
                        shutil.copyfileobj(incoming, outgoing)
                except Exception:
                    if created:
                        destination.unlink(missing_ok=True)
                    raise
            temporary.unlink()
        temporary = None
        emit('Done')
        return 'done', before, after
    except Exception as exc:
        emit(f'Error · {exc}')
        return 'error', 0, 0
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # A cleanup failure must not abort unrelated batch jobs.


def batch_worker_limit(jobs, settings):
    """Honor explicit concurrency; apply the image budget only in Auto mode."""
    if settings.workers > 0:
        return settings.workers
    largest = 1
    for job in jobs:
        try:
            with Image.open(job.source) as image:
                target = target_size(image.size, settings)
                largest = max(largest, image.width * image.height, target[0] * target[1])
        except (OSError, ValueError, Image.DecompressionBombError):
            pass  # Normal per-file error handling still reports unreadable inputs.
    return max(1, min(2, os.cpu_count() or 1, 64_000_000 // largest))


def run_batch(jobs, settings, control, status, progress):
    totals = dict(done=0, error=0, skipped=0, cancelled=0, before=0, after=0)
    iterator = iter(enumerate(jobs))
    workers = batch_worker_limit(jobs, settings)
    with ThreadPoolExecutor(max_workers=workers) as pool:
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
        for _ in range(workers):
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
            while len(pending) < workers and submit():
                pass
    return totals
