"""Build from the locked public dependencies, then smoke-test the frozen app."""
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows release on Windows.')
    if sys.version_info[:3] < (3, 13, 16) or sys.version_info[:2] != (3, 13):
        raise SystemExit('Use Python 3.13.16 or a newer 3.13 security update for release builds.')
    for name, version in [('PySide6-Essentials', '6.10.2'), ('shiboken6', '6.10.2'), ('Pillow', '13.0.0')]:
        if metadata.version(name) != version:
            raise SystemExit(f'Install requirements-build.txt first: expected {name} {version}')
    assets = ROOT / 'assets'
    distribution_root = Path(os.environ.get('OS96_DIST_DIR', str(ROOT / 'dist'))).resolve()
    assets.mkdir(exist_ok=True)
    icon = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill='#2563eb')
    draw.rounded_rectangle((46, 60, 210, 196), radius=12, outline='white', width=10)
    draw.ellipse((158, 86, 181, 109), fill='white')
    draw.polygon([(57, 182), (103, 119), (132, 150), (151, 131), (199, 182)], fill='white')
    icon.save(assets / 'app.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
    icon.save(assets / 'app.png')
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'pip_audit', '--no-deps', '--disable-pip',
        '-r', str(ROOT / 'requirements-release.lock'), '-f', 'json',
        '-o', str(ROOT / 'validation/dependency-audit.json')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
        '--name', 'OS96ImageOptimizer', '--distpath', str(distribution_root), '--icon', str(assets / 'app.ico'),
        '--version-file', str(ROOT / 'packaging/windows-version.txt'),
        '--add-data', f'{assets};assets', '--exclude-module', 'tkinter',
        '--exclude-module', 'numpy', '--exclude-module', 'scipy', '--exclude-module', 'skimage',
        '--exclude-module', 'pip_audit', '--exclude-module', 'matplotlib',
        str(ROOT / 'main.py')], cwd=ROOT, check=True)
    distribution = distribution_root / 'OS96ImageOptimizer'
    # Keep the helper's VC runtime next to the executable rather than depending
    # on a globally installed redistributable or the caller's working directory.
    runtime = distribution / '_internal/VCRUNTIME140.dll'
    if not runtime.exists():
        raise SystemExit('The frozen application is missing its VC runtime.')
    shutil.copy2(runtime, distribution / '_internal/assets/native/VCRUNTIME140.dll')
    licenses = distribution / 'licenses'
    licenses.mkdir(exist_ok=True)
    upstream = ROOT / 'packaging/licenses'
    if not (upstream / 'Qt/LGPL-3.0-only.txt').exists():
        raise SystemExit('Run scripts/fetch_licenses.py before building.')
    shutil.copytree(upstream, licenses, dirs_exist_ok=True)
    manifest = {}
    for package in ('PySide6-Essentials', 'shiboken6', 'Pillow', 'pyinstaller'):
        dist = metadata.distribution(package)
        manifest[package] = dist.version
        target = licenses / package
        target.mkdir(exist_ok=True)
        for item in dist.files or []:
            if any(token in str(item).lower() for token in ('license', 'copying', 'copyright', 'metadata')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    relative = Path(*[part for part in item.parts if part != '..'])
                    destination = target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    for name in ('LICENSE.txt', 'LICENSE'):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            shutil.copy2(source, licenses / 'Python-LICENSE.txt')
            break
    for filename in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'CHANGELOG.md', 'requirements-release.txt'):
        shutil.copy2(ROOT / filename, distribution / filename)
    manifest['Python'] = sys.version
    manifest['application'] = __version__
    manifest['runtime_wheels'] = json.loads((ROOT / 'packaging/runtime-wheels.json').read_text(encoding='utf-8'))
    manifest['signing'] = 'requested' if os.environ.get('OS96_SIGNING_THUMBPRINT') else 'unsigned'
    manifest['source_sha256'] = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [ROOT / 'main.py', *sorted((ROOT / 'optimizer').glob('*.py'))]}
    (distribution / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report = ROOT / 'validation/frozen-selftest.json'
    report.parent.mkdir(exist_ok=True)
    subprocess.run([str(distribution / 'OS96ImageOptimizer.exe'), '--self-test', str(report)], check=True, timeout=60)
    assert json.loads(report.read_text(encoding='utf-8'))['passed']
    if os.environ.get('OS96_SIGNING_THUMBPRINT'):
        subprocess.run(['powershell.exe', '-NoProfile', '-File', str(ROOT / 'scripts/sign_windows.ps1'),
            '-Thumbprint', os.environ['OS96_SIGNING_THUMBPRINT'], '-FilePath', str(distribution / 'OS96ImageOptimizer.exe')], check=True)
    inventory = '\n'.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(distribution).as_posix()
        for path in sorted(distribution.rglob('*')) if path.is_file() and path.name != 'files.sha256')
    (distribution / 'files.sha256').write_text(inventory + '\n', encoding='utf-8')
    archive = shutil.make_archive(str(ROOT / f'dist/OS96ImageOptimizer-{__version__}-portable'), 'zip', distribution.parent, distribution.name)
    checksum = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    Path(archive + '.sha256').write_text(checksum + '  ' + Path(archive).name + '\n', encoding='ascii')
    print(f'Portable build ready: {archive}')


if __name__ == '__main__':
    main()
