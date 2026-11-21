import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
from contextlib import contextmanager

import cv2
import numpy as np
import torch

from full_zip_dataset import FullZipDataset
from train_full_stream import save_checkpoint


@contextmanager
def connect(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


class FullZipTrainingTests(unittest.TestCase):
    def fixture(self, root):
        for sub in ('metadata', 'quality', 'reviewed_full_export_v1'):
            (root / sub).mkdir()
        jpeg = cv2.imencode('.jpg', np.full((48, 64, 3), 120, np.uint8))[1].tobytes()
        shard = root / 'fixture.zip'
        with ZipFile(shard, 'w') as z:
            z.writestr('images/train/allowed.jpg', jpeg)
            z.writestr('labels/train/allowed.txt', '2 .1 .1 .9 .1 .9 .9 .1 .9\n')
        with connect(root / 'metadata/metadata.sqlite') as db:
            db.execute('CREATE TABLE images(id,shard,split)')
            db.executemany('INSERT INTO images VALUES(?,?,?)',
                           [('allowed', shard.name, 'train'), ('quarantined', shard.name, 'train'), ('holdout', shard.name, 'val')])
        with connect(root / 'reviewed_full_export_v1/admission.sqlite') as db:
            db.execute('CREATE TABLE images(id,keep,split)')
            db.executemany('INSERT INTO images VALUES(?,?,?)', [('allowed', 1, 'train'), ('quarantined', 0, 'train'), ('holdout', 1, 'val')])
        with connect(root / 'quality/quality.sqlite') as db:
            db.execute('CREATE TABLE sketches(id,jpeg_sha)')
            db.executemany('INSERT INTO sketches VALUES(?,?)', [(i, hashlib.sha256(jpeg).hexdigest()) for i in ('allowed', 'quarantined', 'holdout')])
        return shard

    def test_admission_excludes_quarantine_and_other_folds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shard = self.fixture(root)
            dataset = FullZipDataset(root, {shard.name: shard}, 'train', 64, augment=True)
            try:
                self.assertEqual([r[0] for r in dataset.rows], ['allowed'])
                a, b = dataset[0], dataset[0]
                self.assertTrue(torch.equal(a['img'], b['img']))
                self.assertTrue(torch.equal(a['masks'], b['masks']))
                self.assertEqual(tuple(a['sem_masks'].shape), (16, 16))
                self.assertEqual(float(a['cls'][0]), 2.)
            finally:
                dataset.close()

    def test_changed_jpeg_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shard = self.fixture(root)
            with connect(root / 'quality/quality.sqlite') as db:
                db.execute("UPDATE sketches SET jpeg_sha='wrong' WHERE id='allowed'")
            dataset = FullZipDataset(root, {shard.name: shard}, 'train', 64)
            try:
                with self.assertRaisesRegex(ValueError, 'JPEG changed'):
                    dataset[0]
            finally:
                dataset.close()

    def test_optimizer_and_within_epoch_position_resume(self):
        torch.manual_seed(7)
        model = torch.nn.Linear(2, 1)
        model.criterion = None
        model.args = SimpleNamespace()
        opt = torch.optim.AdamW(model.parameters(), lr=.01)
        inputs = torch.arange(10, dtype=torch.float32).reshape(5, 2)
        def step(net, optimizer, row):
            optimizer.zero_grad()
            net(row).square().sum().backward()
            optimizer.step()
        for row in inputs[:3]:
            step(model, opt, row)
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp) / 'last.pt'
            save_checkpoint(checkpoint, model, opt, 0, 3, 3, {}, {'dataset': 'fixture'})
            for row in inputs[3:]:
                step(model, opt, row)
            state = torch.load(checkpoint, map_location='cpu', weights_only=False)
            resumed = state['model']
            resumed_opt = torch.optim.AdamW(resumed.parameters(), lr=.01)
            resumed_opt.load_state_dict(state['optimizer'])
            for row in inputs[state['cursor']:]:
                step(resumed, resumed_opt, row)
            for expected, actual in zip(model.parameters(), resumed.parameters()):
                self.assertTrue(torch.equal(expected, actual))
            self.assertEqual(state['epoch'], 0)
            self.assertEqual(state['global_step'], 3)


if __name__ == '__main__':
    unittest.main()
