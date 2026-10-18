"""Build a pinned libjpeg-turbo reference and download a pinned oxipng binary."""
import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'validation/reference-tools'


def download(url, path):
    with urllib.request.urlopen(url, timeout=60) as response:
        path.write_bytes(response.read())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    version = '3.2.0'
    archive = TARGET / 'libjpeg-turbo.tar.gz'
    source_url = f'https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/{version}.tar.gz'
    digest = download(source_url, archive)
    if digest != '980dd81f425082aa6d7c9e47fef27554ce7a9ffc8e2f6e863b97d263c5c50858':
        raise ValueError('Pinned libjpeg-turbo source checksum mismatch')
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if not (TARGET / member.name).resolve().is_relative_to(TARGET.resolve()) or member.issym() or member.islnk():
                raise ValueError('Unsafe source archive entry')
        source.extractall(TARGET)
    build = TARGET / 'jpeg-build'
    subprocess.run(['cmake', '-S', str(TARGET / f'libjpeg-turbo-{version}'), '-B', str(build),
        '-DENABLE_SHARED=OFF', '-DENABLE_STATIC=ON', '-DWITH_SIMD=OFF', '-DWITH_TURBOJPEG=OFF',
        '-DWITH_JAVA=OFF'], check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--target', 'jpegtran-static', '--parallel', '4'], check=True)
    jpegtran = next(build.rglob('jpegtran-static.exe'))
    shutil.copy2(jpegtran, TARGET / 'jpegtran.exe')
    request = urllib.request.Request('https://api.github.com/repos/oxipng/oxipng/releases/tags/v10.2.1', headers={'User-Agent': 'OS96-benchmark'})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    asset = next(asset for asset in release['assets'] if asset['name'].endswith('x86_64-pc-windows-msvc.zip'))
    package = TARGET / 'oxipng.zip'
    png_digest = download(asset['browser_download_url'], package)
    if png_digest != '7e940f83ee46874b73f53031f96a15834cb70b220af27391fb06fe7b4dd798e1':
        raise ValueError('Pinned oxipng binary archive checksum mismatch')
    expected = asset.get('digest', '')
    if expected and expected != 'sha256:' + png_digest:
        raise ValueError('oxipng release checksum mismatch')
    with zipfile.ZipFile(package) as source:
        name = next(name for name in source.namelist() if name.endswith('oxipng.exe'))
        (TARGET / 'oxipng.exe').write_bytes(source.read(name))
    manifest = dict(jpegtran=dict(version=version, source=source_url, source_sha256=digest, simd=False,
        note='Lossless coefficient optimizer; not a quality-matched lossy competitor'),
        oxipng=dict(version=release['tag_name'], source=asset['browser_download_url'], sha256=png_digest))
    (ROOT / 'validation/reference-tools.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
