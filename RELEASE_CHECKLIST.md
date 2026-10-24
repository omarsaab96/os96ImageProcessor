# Windows and macOS 1.0.0rc27 beta

Fix: recognize identified Apple HDR gain maps in JPEGs. All 466 rejected
photos in the supplied report pass the updated reader; the example exports
from 3,616,661 to 1,320,367 bytes and passes the full-resolution quality check.
Re-encoding omits the auxiliary HDR gain map. Real multipage and unidentified
auxiliary images remain protected. Local tests use Python 3.9 / Pillow 11.3;
locked-runtime and frozen-app checks run in the release workflow. Publication
is gated on Windows, both Mac architectures, installer and upstream-source jobs.

# Windows and macOS 1.0.0rc26 beta

Fix: restore Mac Settings through the native Preferences menu role and add
Command-comma. Native macOS inspection confirmed the menu entry is enabled;
opening the action shows the Settings dialog. The local suite ran 80 tests,
with two skips and no failures, using Python 3.9 / Pillow 11.3.
Locked-runtime and frozen-app checks remain gated on the release workflow.
Publish only after Windows, Apple Silicon, Intel Mac, installer and
upstream-source jobs pass.

# Windows and macOS 1.0.0rc25 beta

Fix: recognize embedded MPF preview thumbnails in Sony JPEG photos. All 104
previously rejected photos from the supplied report pass the updated reader;
a full-resolution export succeeded, and the local suite ran 79 tests with
two skips and no failures.
Local testing used Python 3.9 / Pillow 11.3; locked-runtime and frozen-app
verification remain gated on the release workflow. Publish only after Windows,
Apple Silicon, Intel Mac, installer and upstream-source jobs pass.

# Windows and macOS 1.0.0rc24 beta

Current release preparation: 76 local tests pass on Windows. The Windows frozen
application self-test passes. Apple Silicon and Intel macOS builds are prepared
in `.github/workflows/release.yml`; they are not marked verified until those
jobs execute successfully. GitHub publication is gated on both Mac jobs, fresh
Windows installation checks, and matching upstream source packaging.

The user authorized publishing an unsigned GitHub beta. Windows is unsigned;
macOS uses ad-hoc signing, without Developer ID or notarization. Security prompts
are expected and disclosed in the release notes. No signing credentials are
configured. Physical-device and broad display-scaling checks remain manual.

Build and publish using the **Windows and macOS beta** workflow with Publish
selected. It creates Windows installer/portable downloads, separate Apple
Silicon and Intel ZIP/DMG downloads, SHA-256 files, and upstream source archives.
No release is published if any required platform check fails.

The following is historical rc2 evidence, retained for reference. Its counts
and missing-platform statements describe that earlier candidate only.

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
