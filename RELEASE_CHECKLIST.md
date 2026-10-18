# Windows 1.0.0rc2

Local checks are recorded in validation/. A release candidate is deliberately
not labelled a public production release.

Completed in this workspace: 59 passing tests on Python 3.13.16, a stratified
photographic/screenshot/graphics comparison with PSNR/SSIM and established
lossless references, a 1,000-image queue stress run, pinned runtime wheel hashes,
and a clean Python dependency advisory scan. Packaging checks are recorded in
validation/SUMMARY.md and release-readiness.json. Independent
clean-machine checks, physical-device checks, signing, public licensing/source
distribution, and macOS validation remain release gates below.

- Run `python -m unittest discover -s tests -v`.
- Run `python scripts/benchmark.py --count 256`; inspect size, quality, speed, memory.
- Run the benchmark with `--corpus PATH` on a representative collection of
  real photographs, screenshots, ICC profiles, and high-bit-depth images.
  Synthetic results cannot establish competitive photographic compression.
- Build in an isolated environment from requirements-build.txt using
  `python scripts/build_windows.py`.
- Compile packaging/windows.iss with Inno Setup 6.
- Test installer, installed executable self-test, and uninstaller.
- Test on a separate clean Windows machine without Python installed; test
  normal and 200% display scaling and a physical external drive.
- Choose the owner's public distribution license. The current notice reserves
  rights and does not select an open-source license for the owner.
- Check exact bundled licenses and publish matching Qt/PySide source alongside
  binaries before external distribution.
- Sign the application and installer with the owner's code-signing certificate;
  verify signatures and publish SHA-256 checksums after signing.
- macOS is not a release target for this candidate. Build, test, sign and
  notarize on macOS before adding macOS to advertised support.

Build commands:

```powershell
python -m venv .venv-release
.venv-release\Scripts\python -m pip install --index-url https://pypi.org/simple -r requirements-build.txt
.venv-release\Scripts\python scripts/build_windows.py
.venv-release\Scripts\python scripts/package_windows.py
.venv-release\Scripts\python scripts/verify_installer.py
.venv-release\Scripts\python scripts/prepare_sandbox.py
```

Installer documentation: https://jrsoftware.org/ishelp/
PyInstaller build documentation: https://pyinstaller.org/en/stable/usage.html

Use Python 3.13.16 for this release build. The pinned Windows x64 runtime wheels
can be installed using `pip install --require-hashes -r requirements-release.lock`.
The build fails if the runtime advisory scan, unit tests, or frozen-app checks fail.
The owner explicitly chose an unsigned candidate for this session. No signing
step is required for this beta. Optional signing is supported by
scripts/sign_windows.ps1 with a valid code-signing certificate; neither a
self-signed identity nor a trusted signature is fabricated.

Run packaging/verify_clean_windows.ps1 on an independent host or use the generated
Windows Sandbox .wsb. The workflow's fresh-runner-install job runs separately
from the build job and does not set up Python. Prepared scripts do not count as
an executed independent check. The current host lacks Windows Sandbox, and
GitHub is not authenticated in this session; those facts remain visible in
the readiness evidence rather than being marked passed.
