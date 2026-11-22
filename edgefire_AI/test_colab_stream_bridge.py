import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from colab_stream_bridge import create_app, training_jpeg
import cv2
import numpy as np


class BridgeSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.index = self.root / 'index.sqlite'
        self.jpeg, self.label = b'fixture-jpeg-bytes', b'2 .1 .1 .9 .1 .9 .9\n'
        self.shard = self.root / 'shard.zip'
        with ZipFile(self.shard, 'w') as archive:
            archive.writestr('images/train/allowed.jpg', self.jpeg)
            archive.writestr('labels/train/allowed.txt', self.label)
        db = sqlite3.connect(self.index)
        db.execute('CREATE TABLE images(id,shard,jpeg_sha,keep,split)')
        db.executemany('INSERT INTO images VALUES(?,?,?,?,?)', [
            ('allowed', self.shard.name, hashlib.sha256(self.jpeg).hexdigest(), 1, 'train'),
            ('rejected', self.shard.name, 'unused', 0, 'train')])
        db.commit()
        db.close()
        self.token = 'fixture-only-not-a-real-token' * 3
        self.headers = {'Authorization': 'Bearer ' + self.token}
        self.run = self.root / 'run'
        self.package = self.root / 'bootstrap.zip'
        self.package.write_bytes(b'fixture-package')
        self.client = TestClient(create_app(self.index, {self.shard.name: self.shard},
            {'dataset_sha256': 'fixture'}, self.token, self.run, self.package))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_all_routes_require_authentication(self):
        for route in ['/manifest', '/bootstrap.zip', '/sample/train/allowed', '/control', '/artifact/last.pt']:
            self.assertEqual(self.client.get(route).status_code, 401)
        self.assertEqual(self.client.get('/manifest', headers={'Authorization': 'Bearer wrong'}).status_code, 401)

    def test_sample_is_admitted_bound_to_split_and_checksummed(self):
        response = self.client.get('/sample/train/allowed', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        size = struct.unpack('!I', response.content[:4])[0]
        header = json.loads(response.content[4:4+size])
        self.assertEqual(header['dataset_sha256'], 'fixture')
        self.assertEqual(response.content[4+size:], self.jpeg + self.label)
        self.assertEqual(self.client.get('/sample/train/rejected', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/sample/val/allowed', headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/sample/test/allowed', headers=self.headers).status_code, 404)

    def test_checkpoint_digest_and_output_path_are_enforced(self):
        body = b'opaque-checkpoint-never-unpickled'
        headers = {**self.headers, 'X-Content-SHA256': hashlib.sha256(body).hexdigest()}
        response = self.client.put('/artifact/last.pt', content=body, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((self.run / 'last.pt').read_bytes(), body)
        self.assertEqual(self.client.put('/artifact/other.pt', content=body, headers=headers).status_code, 404)
        bad = {**headers, 'X-Content-SHA256': '0'*64}
        self.assertEqual(self.client.put('/artifact/last.pt', content=b'bad', headers=bad).status_code, 422)
        self.assertEqual((self.run / 'last.pt').read_bytes(), body)

    def test_json_identity_and_payload_size_are_checked(self):
        body = b'{"dataset_identity":"wrong"}'
        headers = {**self.headers, 'X-Content-SHA256': hashlib.sha256(body).hexdigest()}
        self.assertEqual(self.client.put('/artifact/status.json', content=body, headers=headers).status_code, 422)
        huge = {**headers, 'Content-Length': str(100*1024**2)}
        self.assertEqual(self.client.put('/artifact/last.pt', content=b'', headers=huge).status_code, 413)

    def test_transport_resize_keeps_aspect_and_full_color(self):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        original = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        decoded = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
        resized = cv2.resize(decoded, (512, 288), interpolation=cv2.INTER_LINEAR)
        result = training_jpeg(original, 512)
        actual = cv2.imdecode(np.frombuffer(result, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(actual.shape, (288, 512, 3))
        self.assertLess(np.abs(actual.astype(float)-resized).mean(), 5.)
        self.assertLess(len(result), len(original))


if __name__ == '__main__':
    unittest.main()
