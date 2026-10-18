"""Optional NASA photographic smoke corpus; never included in app artifacts."""
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def main():
    target = Path('validation/photo-corpus')
    target.mkdir(parents=True, exist_ok=True)
    old = Path('validation/photo-sources.json')
    manifest = json.loads(old.read_text(encoding='utf-8')) if old.exists() else []
    known = {row['nasa_id'] for row in manifest}
    candidates = []
    for query in ('earth ISS', 'astronaut spacewalk', 'forest aerial', 'wildlife',
                  'flowers', 'city skyline', 'mars rover landscape', 'nebula'):
        url = 'https://images-api.nasa.gov/search?' + urllib.parse.urlencode(dict(q=query, media_type='image', page_size=4))
        for item in get_json(url)['collection']['items']:
            if item['data'][0]['nasa_id'] not in known:
                candidates.append(item)
                known.add(item['data'][0]['nasa_id'])
    def fetch(item):
        try:
            data = item['data'][0]
            nasa_id = data['nasa_id']
            assets = get_json('https://images-api.nasa.gov/asset/' + urllib.parse.quote(nasa_id))['collection']['items']
            images = [entry['href'] for entry in assets if entry['href'].lower().endswith('.jpg')]
            image = next((url for url in images if '~large.jpg' in url), next((url for url in images if '~medium.jpg' in url), None))
            if image is None:
                return None
            image = image.replace('http://', 'https://')
            with urllib.request.urlopen(image, timeout=30) as response:
                content = response.read(20_000_001)
            if len(content) > 20_000_000:
                return None
            (target / f'{nasa_id}.jpg').write_bytes(content)
            return dict(nasa_id=nasa_id, title=data['title'], credit=data.get('photographer', data.get('center', 'NASA')), source=image)
        except Exception as exc:
            print(f"Skipped {item['data'][0]['nasa_id']}: {exc}")
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifest.extend(row for row in pool.map(fetch, candidates) if row)
    Path('validation/photo-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Downloaded {len(manifest)} NASA image samples. See validation/photo-sources.json for sources.')


if __name__ == '__main__':
    main()
