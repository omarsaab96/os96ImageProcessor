# Windows 1.0.0rc2 validation

Local unsigned-beta checks passed: **True**. The build uses Python 3.13.16, Pillow 12.3.0, and PySide6/Shiboken 6.10.2.

All 59 tests pass. Tests cover formats, orientation, metadata/ICC, alpha, high-bit-depth grayscale, explicit rejection of unsupported 16-bit color, resizing, cancellation, native optimizer failure/damage/metadata guards, actual Windows file locks, file collisions, presets, reports, and visual comparison.

## Compression evidence

41 unchanged input files were compared with per-file hashes, bytes, timings, PSNR, SSIM, and full-resolution quality checks. The corpus separates camera photographs, illustrations, scientific imagery, screenshots, and generated graphics. The source manifest is photo-sources.json.

| Group | Method | Files | Byte savings | Median per-file savings | Encode seconds | Quality passed | Min SSIM |
|---|---|---:|---:|---:|---:|---:|---:|
| photos | rc1 | 22 | 11.743% | 0.0% | 19.879 | 22 | 0.977978 |
| photos | current | 22 | 15.044% | 5.75% | 20.455 | 22 | 0.977978 |
| photos | reference_lossless | 22 | 5.794% | 4.792% | 5.139 | 22 | 1.0 |
| photos_original | rc1 | 5 | 22.977% | 32.26% | 6.781 | 5 | 0.977978 |
| photos_original | current | 5 | 23.781% | 32.26% | 13.66 | 5 | 0.977978 |
| photos_original | reference_lossless | 5 | 5.475% | 5.042% | 1.694 | 5 | 1.0 |
| photos_web | rc1 | 17 | 0.267% | 0.0% | 13.098 | 17 | 0.99815 |
| photos_web | current | 17 | 6.12% | 4.663% | 6.795 | 17 | 1.0 |
| photos_web | reference_lossless | 17 | 6.12% | 4.663% | 3.445 | 17 | 1.0 |
| screenshots | rc1 | 5 | 5.008% | 4.235% | 0.352 | 5 | 1.0 |
| screenshots | current | 5 | 17.882% | 16.098% | 1.787 | 5 | 1.0 |
| screenshots | reference_lossless | 5 | 20.287% | 18.735% | 2.468 | 5 | 1.0 |

Single-worker encoding times; metrics excluded. rc1 compressor (with common current engine and Pillow) versus current bounded-lossy JPEG plus verified lossless jpegtran/oxipng. Standalone jpegtran/oxipng reference is lossless, NOT a matched-quality lossy competitor. These tools are also used by current, so this is a reference baseline, not independent evidence of beating them. No commercial GUI app claim.

Byte savings are weighted by input bytes; large high-quality originals can dominate totals. Median savings is reported separately. Renderings and scientific imagery are not counted as camera photographs. Lossy candidates are not claimed to be visually identical; use Lossless when exact decoded pixels are required. Center crops with amplified differences were reviewed (photo-quality-crops.png). There was no blinded independent human quality study.

## Reliability and packaging

The 1000-image queue completed in 52.685 seconds with no processing errors, all original hashes unchanged, pause/resume exercised, stopping exercised, and no leftover temporary files. This is a functional stress check, not a hardware-independent throughput promise.

The frozen application and installed application passed Qt/plugin startup, five codec checks, Unicode paths, full-resolution comparison, native helper integrity/execution, and corrupt-input cleanup. The installer/uninstaller passed on the current host. A second PowerShell harness tested both the portable and installed app without Python on PATH, then removed its test installation. These local harness runs are not independent clean-machine evidence.

Runtime wheel hashes, source-code hashes, and the full packaged file inventory were verified. The Python package advisory scan reports no known runtime dependency advisories. This does not cover every bundled native-library issue or certify security. The Python installer signature was verified as belonging to the Python Software Foundation (runtime-provenance.json). The release remains unsigned by explicit owner choice.

The distribution includes native helper notices and a separate versioned upstream source ZIP with checksums. The application owner has not chosen a public distribution license; legal completeness is not certified. No public release was published.

## Independent proof still pending

Not executed in this session. Sandbox feature unavailable; GitHub connection is required for the prepared fresh-runner workflow.

The prepared .wsb maps release inputs read-only, writes reports to a separate directory, and disables networking. The GitHub workflow has a fresh Windows verification job separate from the build job. Neither is marked passed until actually executed. Physical external-drive checks and broader private/professional photo-library testing remain useful before public distribution. macOS remains unvalidated.

Detailed evidence: release-readiness.json, optimizer-comparison.json, OPTIMIZER_COMPARISON.md, dependency-audit.json, build-rc2.log, installer-verification.json, and host-windows-verification/clean-windows-verification.json.
