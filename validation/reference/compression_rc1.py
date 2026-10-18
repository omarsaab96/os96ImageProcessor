"""Offline candidate selection with bounded, full-resolution quality checks."""
from io import BytesIO

from PIL import Image, ImageChops, ImageStat


def quality_ok(reference, decoded):
    """Conservative RGB error limits, including local tiles to protect detail.

    These are numerical safeguards, not a guarantee of visual equivalence.
    Work in strips so comparison memory does not grow with image height.
    """
    if reference.size != decoded.size:
        return False
    total = [0.0, 0.0, 0.0]
    pixels = reference.width * reference.height
    for top in range(0, reference.height, 64):
        box = (0, top, reference.width, min(top + 64, reference.height))
        with reference.crop(box).convert('RGB') as a, decoded.crop(box).convert('RGB') as b:
            with ImageChops.difference(a, b) as difference:
                stats = ImageStat.Stat(difference)
                for channel, value in enumerate(stats.sum2):
                    total[channel] += value
                for left in range(0, reference.width, 64):
                    with difference.crop((left, 0, min(left + 64, reference.width), difference.height)) as tile:
                        if max(ImageStat.Stat(tile).rms) > 6:
                            return False
    return max(value / pixels for value in total) <= 2.5 ** 2


def encode_smart(image, destination, fmt, options, control, emit):
    """Select the smallest passing JPEG; optimize other formats losslessly."""
    if fmt != 'JPEG':
        if fmt == 'PNG':
            options.update(optimize=True, compress_level=9)
        elif fmt == 'WEBP':
            options.update(lossless=True, quality=85, method=4)
        image.save(destination, format=fmt, **options)
        return True

    # CMYK needs profile-aware comparison; preserve its existing maximum-quality path.
    if image.mode not in ('RGB', 'L'):
        image.save(destination, format=fmt, **options)
        return True
    best = None
    fallback = None
    levels = (75, 80, 85, 88, 91, 94, 97, 100)
    low, high = 0, len(levels) - 1
    best_quality = 100
    # Quality generally improves with the encoder quality level. Search that
    # boundary instead of exhaustively encoding every combination. Every chosen
    # candidate still passes the original full-resolution checks.
    while low <= high:
        if not control.checkpoint():
            return False
        middle = (low + high) // 2
        quality = levels[middle]
        emit(f'Optimizing · quality {quality}')
        with BytesIO() as buffer:
            image.save(buffer, format='JPEG', **dict(options, quality=quality,
                       subsampling=0, optimize=True, progressive=False))
            data = buffer.getvalue()
        if quality == 100:
            fallback = data
        with Image.open(BytesIO(data)) as decoded:
            accepted = quality_ok(image, decoded)
        if accepted:
            if best is None or len(data) < len(best):
                best, best_quality = data, quality
            high = middle - 1
        else:
            low = middle + 1
    # Test progressive coding only at the selected quality, rather than at
    # every search step. Check its decoded pixels too.
    if best is not None:
        if not control.checkpoint():
            return False
        with BytesIO() as buffer:
            image.save(buffer, format='JPEG', **dict(options, quality=best_quality,
                       subsampling=0, optimize=True, progressive=True))
            data = buffer.getvalue()
        if len(data) < len(best):
            with Image.open(BytesIO(data)) as decoded:
                if quality_ok(image, decoded):
                    best = data
    # JPEG cannot always meet the limits, even at quality 100. Preserve maximum
    # quality in that case instead of selecting a lower-quality candidate.
    destination.write_bytes(best if best is not None else fallback)
    return True
