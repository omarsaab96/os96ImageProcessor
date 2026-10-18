"""Fetch the upstream open-source Qt license texts omitted from wheel metadata."""
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'packaging/licenses/Qt'
    target.mkdir(parents=True, exist_ok=True)
    url = 'https://api.github.com/repos/qt/qtbase/contents/LICENSES?ref=v6.10.2'
    request = urllib.request.Request(url, headers={'User-Agent': 'OS96-release-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        entries = json.load(response)
    for entry in entries:
        if entry['type'] == 'file':
            with urllib.request.urlopen(entry['download_url'], timeout=60) as response:
                (target / entry['name']).write_bytes(response.read())
    assert (target / 'LGPL-3.0-only.txt').exists()
    print(f'Qt upstream license texts saved to {target}')


if __name__ == '__main__':
    main()
