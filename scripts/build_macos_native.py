"""Build matching native helpers on a Mac; no Homebrew runtime dependencies."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'jpegtran': ('3.2.0', 'https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/3.2.0.tar.gz',
                 '980dd81f425082aa6d7c9e47fef27554ce7a9ffc8e2f6e863b97d263c5c50858'),
    'oxipng': ('10.2.1', 'https://github.com/oxipng/oxipng/archive/refs/tags/v10.2.1.tar.gz',
               '460ccfcdcc9c3877b9f7fae1dfd4f2a3f93d3b2a2af3e3b62ca32b163f923cca'),
}


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Build macOS helpers on macOS.')
    target = ROOT / ('assets/native/macos-' + platform.machine())
    target.mkdir(parents=True, exist_ok=True)
    work = ROOT / 'build/macos-native'
    work.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (version, url, digest) in SOURCES.items():
        archive = work / (name + '.tar.gz')
        with urllib.request.urlopen(url, timeout=60) as incoming, archive.open('wb') as output:
            shutil.copyfileobj(incoming, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise SystemExit(f'{name} source archive checksum mismatch.')
        with tarfile.open(archive) as source:
            folder = work / source.getmembers()[0].name.split('/')[0]
            source.extractall(work, filter='data')
        if name == 'jpegtran':
            build = work / 'jpeg-build'
            subprocess.run(['cmake', '-S', str(folder), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                '-DENABLE_SHARED=OFF', '-DENABLE_STATIC=ON', '-DWITH_SIMD=OFF',
                '-DWITH_TURBOJPEG=OFF', '-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0'], check=True)
            subprocess.run(['cmake', '--build', str(build), '--target', 'jpegtran-static',
                '--parallel', '3'], check=True)
            binary = build / 'jpegtran-static'
        else:
            subprocess.run(['cargo', 'build', '--release', '--locked', '--manifest-path',
                str(folder / 'Cargo.toml')], check=True, env={**os.environ, 'MACOSX_DEPLOYMENT_TARGET': '13.0'})
            binary = folder / 'target/release/oxipng'
        shutil.copy2(binary, target / name)
        (target / name).chmod(0o755)
        # These standalone executables are not signed again by PyInstaller.
        # Sign before hashing so runtime integrity checks cover the shipped bytes.
        subprocess.run(['codesign', '--force', '--sign', '-', str(target / name)], check=True)
        manifest[name] = dict(version=version, source=url,
            source_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            sha256=hashlib.sha256((target / name).read_bytes()).hexdigest())
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
