"""Lock official Windows x64 / Python 3.13 runtime wheels by SHA-256."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    lines = ['# Windows x64 / Python 3.13 runtime wheels. Install with --require-hashes.']
    manifest = []
    for requirement in (ROOT / 'requirements-release.txt').read_text(encoding='utf-8').splitlines():
        if not requirement or requirement.startswith('#'):
            continue
        name, version = requirement.split('==')
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
            data = json.load(response)
        wheel = next(item for item in data['urls'] if item['filename'].endswith('win_amd64.whl') and
                     ('cp313-' in item['filename'] if name.lower() == 'pillow' else 'abi3-' in item['filename']))
        digest = wheel['digests']['sha256']
        lines.append(f'{requirement} --hash=sha256:{digest}')
        manifest.append(dict(name=name, version=version, file=wheel['filename'], source=wheel['url'], sha256=digest))
    (ROOT / 'requirements-release.lock').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (ROOT / 'packaging/runtime-wheels.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
