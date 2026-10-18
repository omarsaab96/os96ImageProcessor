"""Aggregate current, version-matched evidence without claiming unrun checks."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimizer import __version__


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def main():
    folder = ROOT / 'dist/OS96ImageOptimizer'
    manifest = read('dist/OS96ImageOptimizer/build-manifest.json')
    audit = read('validation/dependency-audit.json')
    compare = read('validation/optimizer-comparison.json')
    smoke = read('validation/frozen-selftest.json')
    installer = read('validation/installer-verification.json')
    native_windows = read('validation/host-windows-verification/clean-windows-verification.json')
    stress = read('validation/stress-release.json')
    checks = {
        'runtime_version': manifest.get('application') == __version__ and manifest['Python'].startswith('3.13.16'),
        'runtime_dependency_audit': all(not dependency['vulns'] for dependency in audit['dependencies']),
        'frozen_app_selftest': smoke.get('passed') and smoke.get('version') == __version__,
        'installer_and_uninstaller': installer.get('passed') and installer.get('application', {}).get('version') == __version__,
        'powershell_portable_installer_checks_on_current_host': native_windows.get('passed') and native_windows.get('version') == __version__,
        'stress_queue': stress.get('passed') and stress.get('images', 0) >= 1000,
        'comparison_quality_and_sources': compare.get('sources_unchanged') and not compare.get('errors') and all(row['quality_ok'] for row in compare['files']),
        'comparison_uses_release_runtime': compare.get('python', '').startswith('3.13.16') and compare.get('pillow') == manifest['Pillow'],
        'manifest_matches_current_source': all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in manifest['source_sha256'].items()),
        'all_release_file_hashes': True,
        'artifact_checksums': True,
    }
    for line in (folder / 'files.sha256').read_text(encoding='utf-8').splitlines():
        digest, relative = line.split('  ', 1)
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            checks['all_release_file_hashes'] = False
    for suffix in ('portable.zip', 'Setup.exe', 'upstream-sources.zip'):
        path = ROOT / f'dist/OS96ImageOptimizer-{__version__}-{suffix}'
        expected = Path(str(path) + '.sha256').read_text(encoding='ascii').split()[0]
        checks['artifact_checksums'] &= hashlib.sha256(path.read_bytes()).hexdigest() == expected
    log = (ROOT / 'validation/build-rc2.log').read_text(encoding='utf-8')
    count = re.search(r'Ran (\d+) tests', log)
    checks['unit_tests'] = bool(count and int(count.group(1)) >= 59 and '\nOK\n' in log)
    report = dict(version=__version__, ready_for_unsigned_beta=all(checks.values()), checks=checks,
        unit_tests=int(count.group(1)) if count else None, comparison_summaries=compare['summaries'],
        independent_clean_host='Not executed in this session. Sandbox feature unavailable; GitHub connection is required for the prepared fresh-runner workflow.',
        signing='Unsigned by explicit owner choice; no certificate was available or used.',
        public_distribution='No public release was published. Owner distribution-license decision and independent clean-host/physical-device verification remain open.')
    (ROOT / 'validation/release-readiness.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'comparison_summaries'}, indent=2))
    if not report['ready_for_unsigned_beta']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
