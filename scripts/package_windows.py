"""Compile the installer, optionally sign, and checksum the finished artifact."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def main():
    candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Inno Setup 6/ISCC.exe',
        Path(os.environ.get('ProgramFiles(x86)', '')) / 'Inno Setup 6/ISCC.exe']
    compiler = next((path for path in candidates if path.is_file()), None) or shutil.which('ISCC.exe')
    if not compiler:
        raise SystemExit('Inno Setup 6 compiler not found.')
    subprocess.run([str(compiler), '/Qp', '/DAppVersion=' + __version__, str(ROOT / 'packaging/windows.iss')], check=True)
    installer = ROOT / f'dist/OS96ImageOptimizer-{__version__}-Setup.exe'
    if os.environ.get('OS96_SIGNING_THUMBPRINT'):
        subprocess.run(['powershell.exe', '-NoProfile', '-File', str(ROOT / 'scripts/sign_windows.ps1'),
            '-Thumbprint', os.environ['OS96_SIGNING_THUMBPRINT'], '-FilePath', str(installer)], check=True)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    Path(str(installer) + '.sha256').write_text(digest + '  ' + installer.name + '\n', encoding='ascii')
    print(installer)


if __name__ == '__main__':
    main()
