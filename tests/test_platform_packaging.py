import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from optimizer.native import tool_path


class PlatformPackagingTests(unittest.TestCase):
    def test_macos_selects_matching_architecture_and_checks_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / 'assets/native/macos-arm64'
            folder.mkdir(parents=True)
            helper = folder / 'jpegtran'
            helper.write_bytes(b'correct architecture helper')
            (folder / 'manifest.json').write_text(json.dumps({'jpegtran': {
                'sha256': hashlib.sha256(helper.read_bytes()).hexdigest()}}))
            with patch('optimizer.native.__file__', str(root / 'optimizer/native.py')), \
                    patch('optimizer.native.sys.platform', 'darwin'), \
                    patch('optimizer.native.platform.machine', return_value='arm64'):
                try:
                    tool_path.cache_clear()
                    self.assertEqual(tool_path('jpegtran'), helper)
                    helper.write_bytes(b'tampered')
                    tool_path.cache_clear()
                    self.assertIsNone(tool_path('jpegtran'))
                finally:
                    tool_path.cache_clear()

    def test_macos_never_uses_bundled_windows_helper(self):
        with patch('optimizer.native.sys.platform', 'darwin'), \
                patch('optimizer.native.platform.machine', return_value='missing-architecture'):
            try:
                tool_path.cache_clear()
                self.assertIsNone(tool_path('jpegtran'))
            finally:
                tool_path.cache_clear()
