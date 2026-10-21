"""Offline candidate selection with bounded, full-resolution quality checks."""
from io import BytesIO

from PIL import Image, ImageChops, ImageStat


def jpeg_detail_sample(image):
    """Sample native-resolution detail rather than scaling away JPEG texture."""
    columns = 3 if image.width > 768 else 1
    rows = 3 if image.height > 768 else 1
    width = 256 if columns == 3 else image.width
    height = 256 if rows == 3 else image.height
    sample = Image.new(image.mode, (columns * width, rows * height))
    sample.info.update(image.info)
    for row in range(rows):
        top = round(row * (image.height - height) / max(1, rows - 1))
        for column in range(columns):
            left = round(column * (image.width - width) / max(1, columns - 1))
            with image.crop((left, top, left + width, top + height)) as tile:
                sample.paste(tile, (column * width, row * height))
    return sample


def quality_ok(reference, decoded, *, automatic=False):
    """RGB error limits, including local tiles to protect detail.

    These are numerical safeguards, not a guarantee of visual equivalence.
    Automatic allows modest losses (4 levels RMS globally, 12 locally on
    an eight-bit channel); the strict diagnostic keeps its original limits.
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
                        if max(ImageStat.Stat(tile).rms) > (12 if automatic else 6):
                            return False
        if 'A' in reference.getbands() or 'transparency' in reference.info:
            with reference.crop(box).convert('RGBA') as a, decoded.crop(box).convert('RGBA') as b:
                if a.getchannel('A').tobytes() != b.getchannel('A').tobytes():
                    return False
    return max(value / pixels for value in total) <= (4 if automatic else 2.5) ** 2


def encode_smart(image, destination, fmt, options, control, emit):
    """Select the smallest passing JPEG; optimize other formats losslessly."""
    if fmt != 'JPEG':
        if fmt == 'PNG':
            options.update(optimize=True, compress_level=9)
        elif fmt == 'WEBP':
            options.update(lossless=True, quality=85, method=4, exact=True)
        image.save(destination, format=fmt, **options)
        return True

    # CMYK needs profile-aware comparison; preserve its existing maximum-quality path.
    if image.mode not in ('RGB', 'L'):
        image.save(destination, format=fmt, **options)
        return True
    levels = (60, 65, 70, 75, 80, 85, 88, 91, 94, 97, 100)
    best = None
    best_quality, best_sampling = 100, 0

    # Search native-resolution crops, not the entire photo. Texture is preserved
    # and every final output still gets the original full-resolution checks.
    emit('Optimizing sample')
    with jpeg_detail_sample(image) as sample:
        for sampling in ((0, 1, 2) if image.mode == 'RGB' else (0,)):
            low, high = 0, len(levels) - 1
            first = True
            while low <= high:
                if not control.checkpoint():
                    return False
                middle = 0 if first else (low + high) // 2
                first = False
                quality = levels[middle]
                with BytesIO() as buffer:
                    sample.save(buffer, format='JPEG', quality=quality,
                                subsampling=sampling, optimize=True, progressive=True)
                    data = buffer.getvalue()
                with Image.open(BytesIO(data)) as decoded:
                    accepted = quality_ok(sample, decoded, automatic=True)
                if accepted:
                    if best is None or len(data) < best:
                        best, best_quality, best_sampling = len(data), quality, sampling
                    high = middle - 1
                else:
                    low = middle + 1

    # Usually one full encode. If the sample missed a sensitive region, retry
    # with stronger settings instead of accepting unverified pixel damage.
    candidates = list(dict.fromkeys([
        (best_quality, best_sampling),
        (min(100, best_quality + 10), best_sampling),
        (max(85, best_quality), 0),
        (100, 0),
    ]))
    for quality, sampling in candidates:
        if not control.checkpoint():
            return False
        emit(f'Optimizing full image: quality {quality}, chroma {sampling}')
        image.save(destination, format='JPEG', **dict(options, quality=quality,
                   subsampling=sampling, optimize=True, progressive=True))
        if not control.checkpoint():
            return False
        emit('Checking image quality')
        with Image.open(destination) as decoded:
            accepted = quality_ok(image, decoded, automatic=True)
        if accepted or (quality == 100 and sampling == 0):
            return True
    return True
