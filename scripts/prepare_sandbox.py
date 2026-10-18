"""Prepare a no-network clean Windows Sandbox check, when the OS supports it."""
import json
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def main():
    inputs = ROOT / 'validation/sandbox-input'
    results = ROOT / 'validation/sandbox-results'
    inputs.mkdir(exist_ok=True)
    results.mkdir(exist_ok=True)
    for suffix in ('portable.zip', 'portable.zip.sha256', 'Setup.exe', 'Setup.exe.sha256'):
        name = f'OS96ImageOptimizer-{__version__}-{suffix}'
        shutil.copy2(ROOT / 'dist' / name, inputs / name)
    shutil.copy2(ROOT / 'packaging/verify_clean_windows.ps1', inputs)
    configuration = fr'''<Configuration>
  <Networking>Disable</Networking><vGPU>Disable</vGPU>
  <ClipboardRedirection>Disable</ClipboardRedirection><MemoryInMB>4096</MemoryInMB>
  <MappedFolders>
    <MappedFolder><HostFolder>{escape(str(inputs))}</HostFolder><SandboxFolder>C:\OS96Input</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>{escape(str(results))}</HostFolder><SandboxFolder>C:\OS96Results</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OS96Input\verify_clean_windows.ps1 -ArtifactDirectory C:\OS96Input -ResultDirectory C:\OS96Results -Version {__version__}</Command></LogonCommand>
</Configuration>'''
    path = ROOT / 'validation/OS96-clean-windows.wsb'
    path.write_text(configuration, encoding='utf-8')
    available = shutil.which('WindowsSandbox.exe') is not None
    (ROOT / 'validation/sandbox-status.json').write_text(json.dumps(dict(available=available, executed=False,
        configuration=str(path), reason='Prepared only; launch on a Windows host with Sandbox enabled.'), indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
