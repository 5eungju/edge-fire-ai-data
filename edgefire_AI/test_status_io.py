import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from status_io import write_status


class StatusTests(unittest.TestCase):
    def test_transient_lock_is_retried(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            path.write_text('{"epoch":1}')
            original = Path.replace
            calls = []

            def replacement(source, target):
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError('Windows sharing violation')
                return original(source, target)

            with patch.object(Path, 'replace', replacement):
                self.assertTrue(write_status(path, {'epoch': 2}, sleeper=lambda _: None))
            self.assertEqual(json.loads(path.read_text())['epoch'], 2)
            self.assertEqual(len(calls), 3)

    def test_persistent_lock_keeps_previous_valid_record(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            path.write_text('{"epoch":1}')
            with patch.object(Path, 'replace', side_effect=PermissionError('locked')):
                self.assertFalse(write_status(path, {'epoch': 2}, sleeper=lambda _: None))
            self.assertEqual(json.loads(path.read_text())['epoch'], 1)
            self.assertEqual(list(Path(root).glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
