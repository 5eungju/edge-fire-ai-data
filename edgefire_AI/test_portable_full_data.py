import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

import cv2
import numpy as np

from full_zip_dataset import FullZipDataset
from export_full_portable import verify_index


class PortableFullDataTests(unittest.TestCase):
    def fixture(self, root):
        shard = root / 'fixture.zip'
        jpeg = cv2.imencode('.jpg', np.full((48, 64, 3), 140, np.uint8))[1].tobytes()
        with ZipFile(shard, 'w') as archive:
            archive.writestr('images/train/allowed.jpg', jpeg)
            archive.writestr('labels/train/allowed.txt', '2 .1 .1 .9 .1 .9 .9 .1 .9\n')
        with shard.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        db = sqlite3.connect(root / 'full_dataset.sqlite')
        db.execute('CREATE TABLE images(id TEXT,shard TEXT,split TEXT,jpeg_sha TEXT,keep INTEGER,canonical_site TEXT)')
        db.execute('CREATE TABLE shards(name TEXT,size INTEGER,sha256 TEXT)')
        db.executemany('INSERT INTO images VALUES(?,?,?,?,?,?)',
            [('allowed', shard.name, 'train', hashlib.sha256(jpeg).hexdigest(), 1, 'train-site'),
             ('quarantined', shard.name, 'test', 'unused', 0, 'train-site')])
        db.execute('INSERT INTO shards VALUES(?,?,?)', (shard.name, shard.stat().st_size, sha))
        db.commit()
        admission = hashlib.sha256(b'allowed|1|train|train-site\nquarantined|0|test|train-site\n').hexdigest()
        corpus = hashlib.sha256(f'{shard.name}|{shard.stat().st_size}|{sha}\n'.encode()).hexdigest()
        report = dict(processed_images=2, admission_sha256=admission, retained_split_counts={'train': 1},
                      finalized_shards=1, export_corpus_sha256=corpus)
        return db, shard, report

    def test_portable_keeps_full_mask_and_excludes_quarantine(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db, shard, report = self.fixture(root)
            try:
                self.assertEqual(verify_index(db, report), {'train': 1})
            finally:
                db.close()
            dataset = FullZipDataset(root, {shard.name: shard}, 'train', 64)
            try:
                self.assertEqual(len(dataset), 1)
                self.assertEqual(float(dataset[0]['cls'][0]), 2.)
                self.assertIn(shard, dataset.verified_paths)
            finally:
                dataset.close()

    def test_changed_admission_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            db, _, report = self.fixture(Path(temp))
            try:
                db.execute("UPDATE images SET keep=1 WHERE id='quarantined'")
                with self.assertRaisesRegex(ValueError, 'admission mask differs'):
                    verify_index(db, report)
            finally:
                db.close()

    def test_changed_transferred_zip_rejected_before_decode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db, shard, _ = self.fixture(root)
            db.close()
            with shard.open('ab') as stream:
                stream.write(b'changed-but-still-readable-zip')
            dataset = FullZipDataset(root, {shard.name: shard}, 'train', 64)
            try:
                with self.assertRaisesRegex(ValueError, 'Transferred ZIP hash differs'):
                    dataset[0]
            finally:
                dataset.close()


if __name__ == '__main__':
    unittest.main()
