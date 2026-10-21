"""Lock official platform-specific Python 3.13 runtime wheels by SHA-256."""
import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['windows', 'macos-arm64', 'macos-x86_64'], default='windows')
    target = parser.parse_args().platform
    lines = [f'# {target} / Python 3.13 runtime wheels. Install with --require-hashes.']
    manifest = []
    for requirement in (ROOT / 'requirements-release.txt').read_text(encoding='utf-8').splitlines():
        if not requirement or requirement.startswith('#'):
            continue
        name, version = requirement.split('==')
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
            data = json.load(response)
        suffixes = ('win_amd64.whl',) if target == 'windows' else (target.split('-', 1)[1] + '.whl', 'universal2.whl')
        wheel = next(item for item in data['urls'] if item['filename'].endswith(suffixes) and
                     (target == 'windows' or 'macosx_' in item['filename']) and
                     ('cp313-' in item['filename'] if name.lower() == 'pillow' else 'abi3-' in item['filename']))
        digest = wheel['digests']['sha256']
        lines.append(f'{requirement} --hash=sha256:{digest}')
        manifest.append(dict(name=name, version=version, file=wheel['filename'], source=wheel['url'], sha256=digest))
    suffix = '' if target == 'windows' else '-' + target
    (ROOT / f'requirements-release{suffix}.lock').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (ROOT / f'packaging/runtime-wheels{suffix}.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
