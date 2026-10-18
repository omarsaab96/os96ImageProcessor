"""Install into this workspace, test without Python on PATH, then uninstall."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def main():
    import winreg
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\OS96.ImageOptimizer_is1'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key):
                raise SystemExit('An existing OS96 installation is registered; use a clean host/Sandbox to avoid changing its registration.')
        except FileNotFoundError:
            pass
    installer = ROOT / f'dist/OS96ImageOptimizer-{__version__}-Setup.exe'
    target = (ROOT / 'validation/installed').resolve()
    assert target.is_relative_to((ROOT / 'validation').resolve())
    if target.exists():
        raise SystemExit('Test install directory already exists; inspect it before rerunning.')
    report = dict(passed=False, isolation='Current Windows host, isolated working directory, Python removed from PATH; not a clean-machine VM test')
    subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                    f'/DIR={target}', f'/LOG={ROOT / "validation/install.log"}'], check=True, timeout=120)
    try:
        environment = os.environ.copy()
        environment['PATH'] = str(Path(os.environ['WINDIR']) / 'System32')
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONHOME', None)
        environment['QT_QPA_PLATFORM'] = 'windows'
        with tempfile.TemporaryDirectory(prefix='os96-installed-test-') as temporary:
            result = ROOT / 'validation/installed-selftest.json'
            subprocess.run([str(target / 'OS96ImageOptimizer.exe'), '--self-test', str(result)],
                           cwd=temporary, env=environment, check=True, timeout=60)
            report['application'] = json.loads(result.read_text(encoding='utf-8'))
            assert report['application']['passed']
    finally:
        # The uninstaller only targets the explicitly verified workspace directory.
        assert target.is_relative_to((ROOT / 'validation').resolve())
        subprocess.run([str(target / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        f'/LOG={ROOT / "validation/uninstall.log"}'], check=True, timeout=60)
        for _ in range(50):
            if not target.exists():
                break
            time.sleep(.1)
        report['uninstall_removed_directory'] = not target.exists()
    report['passed'] = bool(report.get('application', {}).get('passed') and report['uninstall_removed_directory'])
    (ROOT / 'validation/installer-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    checksum = hashlib.sha256(installer.read_bytes()).hexdigest()
    Path(str(installer) + '.sha256').write_text(checksum + '  ' + installer.name + '\n', encoding='ascii')
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
