# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 深圳有向空间设计工程有限公司 <https://toiletspace.net>
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'leak' / 'poison.txt'


class LeakScanTest(unittest.TestCase):
    def test_placeholder_exceptions_in_directory_and_zip(self):
        file_id = hashlib.sha256(FIXTURE.name.encode('utf-8')).hexdigest()[:16]
        with tempfile.TemporaryDirectory() as temp:
            archive_path = Path(temp) / 'fixture.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.write(FIXTURE, FIXTURE.name)
            for source, target in (('--dir', FIXTURE.parent), ('--zip', archive_path)):
                with self.subTest(source=source):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / 'tools' / 'leak_scan.py'),
                         source, str(target), '--wordlist',
                         str(ROOT / 'data-internal' / 'customer_names.example.txt')],
                        capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), [
                        f'CUSTOMER file={file_id} line:3',
                        f'PATH file={file_id} line:2',
                        f'PATH file={file_id} line:6',
                        f'SECRET file={file_id} line:1',
                        'leak_scan findings=4',
                    ])


if __name__ == '__main__':
    unittest.main()
