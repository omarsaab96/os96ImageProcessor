"""Compare rc1/current and independent lossless tools on the same untouched inputs.

Reference tools are lossless; current/rc1 use bounded lossy JPEG candidates.
Results are explicitly separated by format and do not claim equal quality modes.
"""
import hashlib
import importlib.util
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageOps, __version__ as pillow_version
from skimage.metrics import structural_similarity, peak_signal_noise_ratio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer.engine import Job, Settings, Control, process
from optimizer.compression import encode_smart, quality_ok


def prepare_corpus():
    corpus = ROOT / 'validation/mixed-corpus'
    corpus.mkdir(parents=True, exist_ok=True)
    for group in ('photos', 'illustrations', 'scientific', 'screenshots', 'graphics'):
        (corpus / group).mkdir(exist_ok=True)
    for source in (ROOT / 'validation/photo-corpus').glob('*.jpg'):
        group = ('illustrations' if 'TTBW-90-' in source.name else 'scientific'
                 if any(tag in source.name for tag in ('PIA12189', 'PIA14417', 'GSFC_20171208')) else 'photos')
        shutil.copy2(source, corpus / group / source.name)
        for old_group in ('photos', 'illustrations', 'scientific'):
            old = corpus / old_group / source.name
            if old_group != group:
                old.unlink(missing_ok=True)
    for source in (ROOT / 'validation/screens').glob('*.png'):
        shutil.copy2(source, corpus / 'screenshots' / source.name)
    with Image.new('RGBA', (800, 600), (200, 20, 90, 0)) as alpha:
        draw = ImageDraw.Draw(alpha)
        draw.ellipse((100, 100, 700, 500), fill=(30, 100, 200, 120))
        alpha.save(corpus / 'graphics/alpha.png', compress_level=1)
        alpha.save(corpus / 'graphics/alpha.webp', lossless=True, exact=True)
    with Image.new('RGB', (800, 600), 'white') as text:
        draw = ImageDraw.Draw(text)
        for y in range(10, 590, 14):
            draw.text((10, y), 'Colored fine text, lines, edges: ABC 0123456789', fill=('red' if y % 3 else 'blue'))
        text.save(corpus / 'graphics/text.jpg', quality=100, subsampling=0)
        text.save(corpus / 'graphics/text.png', compress_level=0)
        text.save(corpus / 'graphics/text.bmp')
    with Image.new('I;16', (800, 600)) as depth:
        pixels = np.arange(800 * 600, dtype=np.uint16).reshape(600, 800)
        with Image.fromarray(pixels) as image:
            image.save(corpus / 'graphics/depth.png', compress_level=0)
            image.save(corpus / 'graphics/depth.tiff')
    return corpus


def metrics(source, output):
    with Image.open(source) as a, Image.open(output) as b:
        with ImageOps.exif_transpose(a) as reference, ImageOps.exif_transpose(b) as decoded:
            accepted = quality_ok(reference, decoded)
            exact = reference.mode == decoded.mode and reference.size == decoded.size and np.array_equal(np.asarray(reference), np.asarray(decoded))
            with reference.convert('RGBA') as ar, decoded.convert('RGBA') as br:
                ra, rb = np.asarray(ar), np.asarray(br)
                alpha = np.array_equal(ra[:, :, 3], rb[:, :, 3])
                rgb_a, rgb_b = ra[:, :, :3], rb[:, :, :3]
                psnr = None if np.array_equal(rgb_a, rgb_b) else float(peak_signal_noise_ratio(rgb_a, rgb_b, data_range=255))
                ssim = float(structural_similarity(rgb_a, rgb_b, data_range=255, channel_axis=-1))
            return dict(quality_ok=accepted and alpha, pixel_exact=exact, alpha_exact=alpha,
                        psnr_db=round(psnr, 4) if psnr is not None else None, ssim=round(ssim, 6))


def native_reference(source, output):
    tools = ROOT / 'validation/reference-tools'
    flags = dict(check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000 if sys.platform == 'win32' else 0)
    if source.suffix.lower() == '.jpg':
        best = source.read_bytes()
        for progressive in (False, True):
            command = [str(tools / 'jpegtran.exe'), '-copy', 'all', '-optimize']
            if progressive:
                command.append('-progressive')
            subprocess.run([*command, '-outfile', str(output), str(source)], **flags)
            candidate = output.read_bytes()
            if len(candidate) < len(best):
                best = candidate
        output.write_bytes(best)
    elif source.suffix.lower() == '.png':
        subprocess.run([str(tools / 'oxipng.exe'), '-o', '4', '--out', str(output), str(source)], **flags)
        if output.stat().st_size > source.stat().st_size:
            shutil.copy2(source, output)
    else:
        return False
    return True


def main():
    corpus = prepare_corpus()
    output = ROOT / 'validation/comparison-outputs'
    output.mkdir(exist_ok=True)
    legacy_path = ROOT / 'validation/reference/compression_rc1.py'
    specification = importlib.util.spec_from_file_location('rc1_compression', legacy_path)
    legacy = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(legacy)
    rows, errors = [], []
    inputs = sorted(path for path in corpus.rglob('*') if path.is_file())
    before_hashes = {str(path.relative_to(corpus)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    for source in inputs:
        relative = source.relative_to(corpus)
        print(f'Comparing {relative}', flush=True)
        for method, encoder in (('rc1', legacy.encode_smart), ('current', encode_smart), ('reference_lossless', None)):
            destination = output / method / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            settings = Settings(output / method, smart=True, overwrite=True, workers=1)
            start = time.perf_counter()
            if encoder is None:
                if not native_reference(source, destination):
                    continue
                result = 'done'
            else:
                messages = []
                with patch('optimizer.engine.encode_smart', encoder):
                    if method == 'rc1':
                        with patch('optimizer.engine.optimize_native', lambda *_: None), patch('optimizer.engine.prefer_lossless_jpeg', lambda *_: False):
                            result = process(Job(source, relative), settings, Control(), messages.append)[0]
                    else:
                        result = process(Job(source, relative), settings, Control(), messages.append)[0]
                if result != 'done':
                    errors.append(dict(file=str(relative), method=method, messages=messages))
                    continue
            elapsed = time.perf_counter() - start
            row = dict(file=relative.as_posix(), group=relative.parts[0], format=source.suffix[1:].upper(), method=method,
                source_kind='original_asset' if relative.name.startswith('original-') else 'web_rendition' if relative.parts[0] == 'photos' else 'fixture',
                before=source.stat().st_size, after=destination.stat().st_size, seconds=round(elapsed, 4), **metrics(source, destination))
            rows.append(row)
    unchanged = before_hashes == {str(path.relative_to(corpus)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    summaries = []
    for group in ('all', 'photos', 'photos_original', 'photos_web', 'illustrations', 'scientific', 'screenshots', 'graphics', 'JPEG', 'PNG'):
        for method in ('rc1', 'current', 'reference_lossless'):
            selected = [row for row in rows if row['method'] == method and
                (group == 'all' or row['group'] == group or
                 (group == 'photos_original' and row['group'] == 'photos' and row['source_kind'] == 'original_asset') or
                 (group == 'photos_web' and row['group'] == 'photos' and row['source_kind'] == 'web_rendition') or
                 (group == 'JPEG' and row['format'] == 'JPG') or (group == 'PNG' and row['format'] == 'PNG'))]
            if not selected:
                continue
            before, after = sum(row['before'] for row in selected), sum(row['after'] for row in selected)
            summaries.append(dict(group=group, method=method, files=len(selected), before=before, after=after,
                saved_percent=round(100 * (before - after) / before, 3), seconds=round(sum(row['seconds'] for row in selected), 3),
                median_saved_percent=round(statistics.median(100 * (row['before'] - row['after']) / row['before'] for row in selected), 3),
                files_reduced=sum(row['after'] < row['before'] for row in selected),
                quality_passed=sum(row['quality_ok'] for row in selected), min_ssim=min(row['ssim'] for row in selected),
                pixel_exact=sum(row['pixel_exact'] for row in selected)))
    report = dict(methodology='Single-worker encoding times; metrics excluded. rc1 compressor (with common current engine and Pillow) versus current bounded-lossy JPEG plus verified lossless jpegtran/oxipng. Standalone jpegtran/oxipng reference is lossless, NOT a matched-quality lossy competitor. These tools are also used by current, so this is a reference baseline, not independent evidence of beating them. No commercial GUI app claim.',
        pillow=pillow_version,
        python=sys.version,
        source_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / 'optimizer').glob('*.py')},
        corpus_files=len(inputs), source_hashes=before_hashes, sources_unchanged=unchanged,
        reference_rc1_sha256=hashlib.sha256(legacy_path.read_bytes()).hexdigest(), summaries=summaries, files=rows, errors=errors)
    (ROOT / 'validation/optimizer-comparison.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# Optimizer comparison', '', report['methodology'], '', '| Group | Method | Files | Saved | Seconds | Quality pass | Min SSIM |', '|---|---|---:|---:|---:|---:|---:|']
    for row in summaries:
        lines.append(f"| {row['group']} | {row['method']} | {row['files']} | {row['saved_percent']}% | {row['seconds']} | {row['quality_passed']} | {row['min_ssim']} |")
    (ROOT / 'validation/OPTIMIZER_COMPARISON.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    changed = sorted([row for row in rows if row['method'] == 'current' and row['group'] == 'photos' and row['after'] < row['before']], key=lambda row: row['ssim'])[:6]
    if changed:
        sheet = Image.new('RGB', (1536, len(changed) * 540), 'white')
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(changed):
            with Image.open(corpus / row['file']) as a, Image.open(output / 'current' / row['file']) as b:
                with ImageOps.exif_transpose(a).convert('RGB') as ar, ImageOps.exif_transpose(b).convert('RGB') as br:
                    left, top = max(0, (ar.width - 512) // 2), max(0, (ar.height - 512) // 2)
                    box = (left, top, left + 512, top + 512)
                    ac, bc = ar.crop(box), br.crop(box)
                    diff = ImageChops.difference(ac, bc).point(lambda value: min(255, value * 8))
                    for x, picture in enumerate((ac, bc, diff)):
                        sheet.paste(picture, (x * 512, index * 540 + 28))
                        picture.close()
                    draw.text((4, index * 540 + 6), f"{row['file']} | SSIM {row['ssim']} | left: original, middle: output, right: difference x8", fill='black')
        sheet.save(ROOT / 'validation/photo-quality-crops.png')
        sheet.close()
    print(json.dumps(summaries, indent=2))
    if errors or not unchanged or any(not row['quality_ok'] for row in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
