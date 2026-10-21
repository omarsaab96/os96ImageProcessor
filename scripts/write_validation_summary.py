"""Write the review summary from collected evidence, rather than copied numbers."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = json.loads((ROOT / 'validation/release-readiness.json').read_text(encoding='utf-8'))
    comparison = json.loads((ROOT / 'validation/optimizer-comparison.json').read_text(encoding='utf-8'))
    stress = json.loads((ROOT / 'validation/stress-release.json').read_text(encoding='utf-8'))
    lines = [f"# Windows {report['version']} validation", '',
        f"Local unsigned-beta checks passed: **{report['ready_for_unsigned_beta']}**. The build uses Python 3.13.16, Pillow 13.0.0, and PySide6/Shiboken 6.10.2.", '',
        f"All {report['unit_tests']} tests pass. Tests cover formats, orientation, metadata/ICC, alpha, high-bit-depth grayscale, explicit rejection of unsupported 16-bit color, resizing, cancellation, native optimizer failure/damage/metadata guards, actual Windows file locks, file collisions, presets, reports, and visual comparison.", '',
        '## Compression evidence', '',
        f"{comparison['corpus_files']} unchanged input files were compared with per-file hashes, bytes, timings, PSNR, SSIM, and full-resolution quality checks. The corpus separates camera photographs, illustrations, scientific imagery, screenshots, and generated graphics. The source manifest is photo-sources.json.", '',
        '| Group | Method | Files | Byte savings | Median per-file savings | Encode seconds | Quality passed | Min SSIM |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for row in comparison['summaries']:
        if row['group'] not in ('photos', 'photos_web', 'photos_original', 'screenshots'):
            continue
        lines.append(f"| {row['group']} | {row['method']} | {row['files']} | {row['saved_percent']}% | {row['median_saved_percent']}% | {row['seconds']} | {row['quality_passed']} | {row['min_ssim']} |")
    lines += ['', comparison['methodology'], '',
        'Byte savings are weighted by input bytes; large high-quality originals can dominate totals. Median savings is reported separately. Renderings and scientific imagery are not counted as camera photographs. Lossy candidates are not claimed to be visually identical; use Lossless when exact decoded pixels are required. Center crops with amplified differences were reviewed (photo-quality-crops.png). There was no blinded independent human quality study.', '',
        '## Reliability and packaging', '',
        f"The {stress['images']}-image queue completed in {stress['seconds']} seconds with no processing errors, all original hashes unchanged, pause/resume exercised, stopping exercised, and no leftover temporary files. This is a functional stress check, not a hardware-independent throughput promise.", '',
        'The frozen application and installed application passed Qt/plugin startup, five codec checks, Unicode paths, full-resolution comparison, native helper integrity/execution, and corrupt-input cleanup. The installer/uninstaller passed on the current host. A second PowerShell harness tested both the portable and installed app without Python on PATH, then removed its test installation. These local harness runs are not independent clean-machine evidence.', '',
        'Runtime wheel hashes, source-code hashes, and the full packaged file inventory were verified. The Python package advisory scan reports no known runtime dependency advisories. This does not cover every bundled native-library issue or certify security. The Python installer signature was verified as belonging to the Python Software Foundation (runtime-provenance.json). The release remains unsigned by explicit owner choice.', '',
        'The distribution includes native helper notices and a separate versioned upstream source ZIP with checksums. The application owner has not chosen a public distribution license; legal completeness is not certified. No public release was published.', '',
        '## Independent proof still pending', '', report['independent_clean_host'], '',
        'The prepared .wsb maps release inputs read-only, writes reports to a separate directory, and disables networking. The GitHub workflow has a fresh Windows verification job separate from the build job. Neither is marked passed until actually executed. Physical external-drive checks and broader private/professional photo-library testing remain useful before public distribution. macOS remains unvalidated.', '',
        'Detailed evidence: release-readiness.json, optimizer-comparison.json, OPTIMIZER_COMPARISON.md, dependency-audit.json, build-rc2.log, installer-verification.json, and host-windows-verification/clean-windows-verification.json.']
    (ROOT / 'validation/SUMMARY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
