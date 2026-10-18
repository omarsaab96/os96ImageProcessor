"""Copy the verified reference builds and their upstream licenses into assets."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'validation/reference-tools'
    target = ROOT / 'assets/native'
    target.mkdir(parents=True, exist_ok=True)
    versions = json.loads((ROOT / 'validation/reference-tools.json').read_text(encoding='utf-8'))
    manifest = {}
    for name in ('jpegtran', 'oxipng'):
        path = target / f'{name}.exe'
        shutil.copy2(source / path.name, path)
        manifest[name] = dict(version=versions[name]['version'], sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source=versions[name]['source'])
    licenses = ROOT / 'packaging/licenses/native'
    licenses.mkdir(parents=True, exist_ok=True)
    jpeg_source = source / ('libjpeg-turbo-' + versions['jpegtran']['version'])
    for name in ('LICENSE.md', 'README.ijg', 'README.md'):
        shutil.copy2(jpeg_source / name, licenses / ('libjpeg-turbo-' + name))
    with zipfile.ZipFile(source / 'oxipng.zip') as package:
        for name in package.namelist():
            if 'license' in name.lower() and not name.endswith('/'):
                (licenses / ('oxipng-' + Path(name).name)).write_bytes(package.read(name))
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
