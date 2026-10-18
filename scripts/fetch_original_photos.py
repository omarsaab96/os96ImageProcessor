"""Add a small, bounded set of original camera assets without resampling them."""
import json
import urllib.request
from io import BytesIO
from pathlib import Path
from PIL import Image


def main():
    manifest_path = Path('validation/photo-sources.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    existing = {row.get('local_file') for row in manifest if row.get('variant') == 'original_asset'}
    added = 0
    for row in list(manifest):
        if row.get('variant') == 'original_asset':
            continue
        if 'TTBW-90-' in row['nasa_id'] or any(tag in row['nasa_id'] for tag in ('PIA12189', 'PIA14417', 'GSFC_20171208')):
            continue
        if 'original-' + row['nasa_id'] + '.jpg' in existing:
            continue
        url = row['source'].replace('http://', 'https://').replace('~large.jpg', '~orig.jpg').replace('~medium.jpg', '~orig.jpg')
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read(12_000_001)
            if len(content) > 12_000_000:
                continue
            with Image.open(BytesIO(content)) as image:
                if image.format != 'JPEG' or image.width * image.height > 8_000_000:
                    continue
                dimensions = image.size
            name = 'original-' + row['nasa_id'] + '.jpg'
            Path('validation/photo-corpus', name).write_bytes(content)
            manifest.append(dict(row, source=url, variant='original_asset', local_file=name, dimensions=dimensions))
            added += 1
            if added == 4:
                break
        except Exception as exc:
            print(f"Skipped original {row['nasa_id']}: {exc}")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Added {added} original photographic assets, without altering dimensions or quality.')


if __name__ == '__main__':
    main()
