"""Optional, bundled lossless optimizers. Every result is decoded and compared."""
import hashlib
import json
import os
import platform
import sys
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image


@lru_cache(maxsize=2)
def tool_path(name):
    folder = Path(__file__).resolve().parent.parent / 'assets/native'
    if sys.platform == 'darwin':
        folder /= 'macos-' + platform.machine()
        executable = folder / name
    elif sys.platform == 'win32':
        executable = folder / f'{name}.exe'
    else:
        return None
    try:
        expected = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))[name]['sha256']
        if hashlib.sha256(executable.read_bytes()).hexdigest() == expected:
            return executable
    except (OSError, KeyError, ValueError):
        pass
    return None


def pixel_equal(a, b):
    if a.size != b.size:
        return False
    high_depth = a.mode in ('I', 'I;16', 'I;16B', 'I;16L') or b.mode in ('I', 'I;16', 'I;16B', 'I;16L')
    mode = 'I' if high_depth else 'CMYK' if a.mode == 'CMYK' else 'RGBA'
    for top in range(0, a.height, 64):
        box = (0, top, a.width, min(a.height, top + 64))
        with a.crop(box).convert(mode) as left, b.crop(box).convert(mode) as right:
            if left.tobytes() != right.tobytes():
                return False
    return True


def optimize_native(path, fmt, control, emit):
    """Keep only smaller, pixel-identical output, with metadata/profile intact."""
    name = 'jpegtran' if fmt == 'JPEG' else 'oxipng' if fmt == 'PNG' else None
    executable = tool_path(name) if name else None
    if executable is None or not control.checkpoint():
        return
    try:
        with tempfile.TemporaryDirectory(prefix='.os96-native-', dir=path.parent) as folder:
            candidate = Path(folder) / path.name
            variants = (False, True) if fmt == 'JPEG' else (False,)
            environment = os.environ.copy()
            environment['PATH'] = str(Path(__file__).resolve().parent.parent) + os.pathsep + environment.get('PATH', '')
            for progressive in variants:
                if not control.checkpoint():
                    return
                if fmt == 'JPEG':
                    arguments = ['-copy', 'all', '-optimize'] + (['-progressive'] if progressive else [])
                    arguments += ['-outfile', str(candidate), str(path)]
                else:
                    arguments = ['-o', '2', '--out', str(candidate), str(path)]
                emit('Optimizing lossless coding')
                subprocess.run([str(executable), *arguments], check=True, timeout=120,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment,
                    creationflags=0x08000000 if os.name == 'nt' else 0)
                if candidate.stat().st_size >= path.stat().st_size:
                    continue
                with Image.open(path) as reference, Image.open(candidate) as output:
                    same = pixel_equal(reference, output)
                    same = same and reference.info.get('icc_profile') == output.info.get('icc_profile')
                    same = same and dict(reference.getexif()) == dict(output.getexif())
                    same = same and all(reference.info.get(key) == output.info.get(key) for key in ('dpi', 'xmp', 'exif'))
                    if fmt == 'PNG':
                        same = same and all(output.info.get(key) == value for key, value in reference.info.items() if isinstance(value, str))
                if same and control.checkpoint():
                    os.replace(candidate, path)
    except (OSError, subprocess.SubprocessError, ValueError):
        # Optimizer absence, timeout, or failure leaves the valid Pillow output.
        return
