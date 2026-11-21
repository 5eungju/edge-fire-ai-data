import unittest
import tempfile
import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock
from audit_archive_integrity import verify_member
from split_zip_reader import ZipReader, MemberIntegrityError


class IntegrityTests(unittest.TestCase):
    def test_transient_crc_error_is_retried(self):
        reader = Mock()
        reader.read.side_effect = [ValueError('Member CRC/size mismatch'), b'valid']
        self.assertIsNone(verify_member(reader, object()))
        self.assertEqual(reader.read.call_count, 2)
        reader.close.assert_called_once()

    def test_persistent_crc_error_is_recorded(self):
        reader = Mock()
        reader.read.side_effect = ValueError('Member CRC/size mismatch')
        self.assertEqual(verify_member(reader, object()), 'Member CRC/size mismatch')

    def test_device_error_is_not_misclassified_as_bad_data(self):
        reader = Mock()
        reader.read.side_effect = OSError('device disconnected')
        with self.assertRaises(OSError):
            verify_member(reader, object())
        self.assertEqual(reader.read.call_count, 1)

    def test_deflate_failure_is_retried_with_payload_fingerprint(self):
        reader = Mock()
        reader.read.side_effect = MemberIntegrityError('Deflate stream error', 'stable-sha')
        self.assertIn('stable-sha', verify_member(reader, object()))
        self.assertEqual(reader.read.call_count, 2)

    def test_unstable_reads_stop_without_corruption_classification(self):
        reader = Mock()
        reader.read.side_effect = [MemberIntegrityError('Deflate stream error','one'), MemberIntegrityError('Deflate stream error','two')]
        with self.assertRaises(OSError):
            verify_member(reader, object())

    def test_real_zip_checkpoint_resume_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            index=root/'index.sqlite'
            connection=sqlite3.connect(index)
            connection.executescript('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);'
                'CREATE TABLE members(role TEXT,key TEXT,name TEXT,disk INT,offset INT,compressed INT,uncompressed INT,method INT,crc INT,flags INT);')
            fingerprints={}
            for role in ['VS','TS']:
                path=root/(role+'.zip')
                with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('first.jpg',b'CRC fixture payload, not a pixel-decoding test')
                    archive.writestr('second.jpg',b'another CRC fixture payload')
                reader=ZipReader(path)
                fingerprints[role]=[{'path':str(path),'bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns}]
                for entry in reader.entries():
                    connection.execute('INSERT INTO members VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (role,entry.name,entry.name,entry.disk,entry.offset,entry.compressed,entry.uncompressed,entry.method,entry.crc,entry.flags))
                reader.close()
            connection.execute('INSERT INTO settings VALUES(?,?)',('fingerprint',json.dumps(fingerprints)))
            connection.commit();connection.close()
            output=root/'audit'
            command=[sys.executable,str(Path(__file__).with_name('audit_archive_integrity.py')),'--index',str(index),'--output',str(output)]
            subprocess.run(command,check=True,capture_output=True)
            first=json.loads((output/'summary.json').read_text(encoding='utf8'))
            subprocess.run(command,check=True,capture_output=True)
            second=json.loads((output/'summary.json').read_text(encoding='utf8'))
            self.assertEqual(first['checked_images'],4)
            self.assertEqual(second['checked_images'],4)
            self.assertEqual(second['failed_images'],0)
            self.assertEqual(second['original_archives'],fingerprints)
            with (root/'TS.zip').open('ab') as stream:stream.write(b'x')
            changed=subprocess.run(command,capture_output=True)
            self.assertNotEqual(changed.returncode,0)


if __name__ == '__main__':
    unittest.main()
