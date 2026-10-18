"""Prepare versioned upstream source archives alongside the unsigned binaries."""
import hashlib
import json
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'dist/upstream-sources'
    folder.mkdir(parents=True, exist_ok=True)
    sources = {
        'qtbase-6.10.2.tar.gz': 'https://github.com/qt/qtbase/archive/refs/tags/v6.10.2.tar.gz',
        'qtsvg-6.10.2.tar.gz': 'https://github.com/qt/qtsvg/archive/refs/tags/v6.10.2.tar.gz',
        'pyside-setup-6.10.2.tar.gz': 'https://github.com/pyside/pyside-setup/archive/refs/tags/v6.10.2.tar.gz',
        'pillow-12.3.0.tar.gz': 'https://github.com/python-pillow/Pillow/archive/refs/tags/12.3.0.tar.gz',
        'libjpeg-turbo-3.2.0.tar.gz': 'https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/3.2.0.tar.gz',
        'oxipng-10.2.1.tar.gz': 'https://github.com/oxipng/oxipng/archive/refs/tags/v10.2.1.tar.gz',
        'cpython-3.13.16.tar.xz': 'https://www.python.org/ftp/python/3.13.16/Python-3.13.16.tar.xz',
    }
    def fetch(item):
        name, url = item
        path = folder / name
        if path.exists():
            return dict(file=name, source=url, bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with urllib.request.urlopen(url, timeout=60) as incoming, path.open('wb') as output:
            while block := incoming.read(1024 * 1024):
                output.write(block)
        return dict(file=name, source=url, bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with ThreadPoolExecutor(max_workers=3) as pool:
        manifest = list(pool.map(fetch, sources.items()))
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (folder / 'README.txt').write_text('Upstream versioned sources for this release candidate. Keep this source bundle alongside binary downloads. Qt is dynamically linked and can be replaced with compatible modified builds. See THIRD_PARTY_NOTICES.md for build links. These upstream archives are not a certification that all public-distribution obligations have been reviewed.\n', encoding='utf-8')
    package = ROOT / 'dist/OS96ImageOptimizer-1.0.0rc2-upstream-sources.zip'
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(folder.iterdir()):
            archive.write(path, 'upstream-sources/' + path.name)
    Path(str(package) + '.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest() + '  ' + package.name + '\n', encoding='ascii')
    (ROOT / 'validation/upstream-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(package)


if __name__ == '__main__':
    main()
