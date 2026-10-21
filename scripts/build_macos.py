"""Create and verify an ad-hoc-signed macOS beta app and drag-to-install DMG."""
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Build the macOS release on a Mac or macOS Actions runner.')
    if sys.version_info[:2] != (3, 13) or sys.version_info[:3] < (3, 13, 16):
        raise SystemExit('Use Python 3.13.16 or a newer 3.13 security update.')
    architecture = platform.machine()
    if architecture not in ('arm64', 'x86_64'):
        raise SystemExit('Expected an Apple Silicon or Intel Mac.')
    lock = ROOT / f'requirements-release-macos-{architecture}.lock'
    for name, version in [('PySide6-Essentials', '6.10.2'), ('shiboken6', '6.10.2'), ('Pillow', '13.0.0')]:
        if metadata.version(name) != version:
            raise SystemExit(f'Expected {name} {version}; install {lock.name}.')
    helper_folder = ROOT / f'assets/native/macos-{architecture}'
    if not (helper_folder / 'manifest.json').exists():
        raise SystemExit('Run scripts/build_macos_native.py first.')
    output = ROOT / f'dist/macos-{architecture}'
    output.mkdir(parents=True, exist_ok=True)
    (ROOT / 'validation').mkdir(exist_ok=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'pip_audit', '--no-deps', '--disable-pip', '-r', str(lock),
        '-f', 'json', '-o', str(ROOT / f'validation/macos-{architecture}-audit.json')], check=True)
    with Image.open(ROOT / 'assets/app.png') as icon:
        icon.resize((1024, 1024), Image.Resampling.LANCZOS).save(ROOT / 'assets/app.icns')
    # Stage only assets for this platform; never include Windows .exe helpers.
    assets = ROOT / 'build/macos-assets'
    assets.mkdir(parents=True, exist_ok=True)
    for name in ('app.png', 'app.ico', 'app.icns', 'checkbox-check.svg'):
        shutil.copy2(ROOT / 'assets' / name, assets / name)
    shutil.copytree(helper_folder, assets / 'native' / helper_folder.name, dirs_exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
        '--name', 'OS96ImageOptimizer', '--distpath', str(output), '--icon', str(assets / 'app.icns'),
        '--osx-bundle-identifier', 'com.os96.imageoptimizer', '--target-architecture', architecture,
        '--add-data', f'{assets}:assets', '--exclude-module', 'tkinter', '--exclude-module', 'numpy',
        '--exclude-module', 'scipy', '--exclude-module', 'skimage', '--exclude-module', 'pip_audit',
        '--exclude-module', 'matplotlib', str(ROOT / 'main.py')], cwd=ROOT, check=True)
    bundle = output / 'OS96ImageOptimizer.app'
    resources = bundle / 'Contents/Resources'
    with (bundle / 'Contents/Info.plist').open('rb') as source:
        info = plistlib.load(source)
    build_number = __version__.replace('rc', 'b')
    info.update(CFBundleShortVersionString=__version__.split('rc')[0], CFBundleVersion=build_number,
                NSHighResolutionCapable=True, LSMinimumSystemVersion='13.0')
    with (bundle / 'Contents/Info.plist').open('wb') as destination:
        plistlib.dump(info, destination)
    licenses = resources / 'licenses'
    shutil.copytree(ROOT / 'packaging/licenses', licenses, dirs_exist_ok=True)
    versions = {}
    for package in ('PySide6-Essentials', 'shiboken6', 'Pillow', 'pyinstaller'):
        distribution = metadata.distribution(package)
        versions[package] = distribution.version
        for item in distribution.files or []:
            if any(token in str(item).lower() for token in ('license', 'copying', 'copyright', 'metadata')):
                source = Path(distribution.locate_file(item))
                if source.is_file():
                    destination = licenses / package / Path(*[part for part in item.parts if part != '..'])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    for filename in ('LICENSE.txt', 'LICENSE'):
        source = Path(sys.base_prefix) / filename
        if source.is_file():
            shutil.copy2(source, licenses / 'Python-LICENSE.txt')
            break
    for filename in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md', 'CHANGELOG.md', lock.name):
        shutil.copy2(ROOT / filename, resources / filename)
    # Freezing can adjust Mach-O binaries. Hash the final helper bytes, then
    # renew only the outer bundle signature without modifying nested helpers.
    manifest_path = resources / 'assets/native' / helper_folder.name / 'manifest.json'
    helpers = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name in helpers:
        helpers[name]['sha256'] = hashlib.sha256((manifest_path.parent / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(helpers, indent=2), encoding='utf-8')
    versions.update(application=__version__, Python=sys.version, architecture=architecture,
        signing='Ad-hoc only; no Developer ID or Apple notarization',
        runtime_wheels=json.loads((ROOT / f'packaging/runtime-wheels-macos-{architecture}.json').read_text()),
        sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in [ROOT / 'main.py', *sorted((ROOT / 'optimizer').glob('*.py'))]})
    (resources / 'build-manifest.json').write_text(json.dumps(versions, indent=2), encoding='utf-8')
    subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    executable = bundle / 'Contents/MacOS/OS96ImageOptimizer'
    report = ROOT / f'validation/macos-{architecture}-selftest.json'
    subprocess.run([str(executable), '--self-test', str(report)], check=True, timeout=120)
    if not json.loads(report.read_text(encoding='utf-8'))['passed']:
        raise SystemExit('The frozen macOS app did not pass its self-test.')
    # ditto preserves framework symlinks and executable permissions in the ZIP.
    stem = ROOT / f'dist/OS96ImageOptimizer-{__version__}-macos-{architecture}'
    archive = Path(str(stem) + '.zip')
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle), str(archive)], check=True)
    stage = output / 'dmg'
    stage.mkdir(exist_ok=True)
    subprocess.run(['ditto', str(bundle), str(stage / bundle.name)], check=True)
    applications = stage / 'Applications'
    if not applications.exists():
        applications.symlink_to('/Applications')
    dmg = Path(str(stem) + '.dmg')
    subprocess.run(['hdiutil', 'create', '-ov', '-volname', 'OS96 Image Optimizer', '-srcfolder', str(stage),
        '-format', 'UDZO', str(dmg)], check=True)
    subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
    for artifact in (archive, dmg):
        Path(str(artifact) + '.sha256').write_text(hashlib.sha256(artifact.read_bytes()).hexdigest()
            + '  ' + artifact.name + '\n', encoding='ascii')
    print(f'macOS {architecture} beta ready: {dmg}')


if __name__ == '__main__':
    main()
