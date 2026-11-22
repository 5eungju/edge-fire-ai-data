"""GPU-side client for the authenticated laptop bridge. Never contains secrets."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import struct
import time
from urllib.parse import urlparse

import requests

from export_full_portable import approve_index
from full_zip_dataset import FullZipDataset, require


class BridgeConnection:
    def __init__(self, config):
        self.config = json.loads(Path(config).read_text('utf8')) if not isinstance(config, dict) else config
        self.url = self.config['url'].rstrip('/')
        parsed = urlparse(self.url)
        require(parsed.scheme == 'https' and parsed.hostname and parsed.hostname.endswith('.trycloudflare.com'),
                'Bridge requires its explicit temporary HTTPS hostname')
        require(not parsed.username and not parsed.password and not parsed.query and parsed.path in ('', '/'), 'Invalid bridge URL')
        self.headers = {'Authorization': 'Bearer ' + self.config['token']}
        self.preprocess = self.config.get('preprocess', dict(train='original', val='original'))

    def get(self, path):
        for attempt in range(4):
            try:
                response = requests.get(self.url + path, headers=self.headers, timeout=(15, 180), allow_redirects=False)
                response.raise_for_status()
                require(response.status_code == 200, 'Unexpected redirect or response')
                return response
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)

    def sync(self, path):
        path = Path(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        for attempt in range(4):
            try:
                with path.open('rb') as stream:
                    response = requests.put(self.url + '/artifact/' + path.name, data=stream,
                        headers={**self.headers, 'X-Content-SHA256': digest, 'Content-Length': str(path.stat().st_size)},
                        timeout=(15, 240), allow_redirects=False)
                response.raise_for_status()
                receipt = response.json()
                require(receipt.get('stored') and receipt.get('sha256') == digest, 'C: checkpoint receipt mismatch')
                return receipt
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(1 + attempt)


def approve_remote(root, connection):
    root, identity, shards = approve_index(root)
    health = connection.get('/manifest').json()
    require(health['identity'] == identity, 'Laptop bridge dataset identity differs')
    require(health.get('preprocess', dict(train='original', val='original')) == connection.preprocess,
            'Transport preprocessing differs; use an explicit checkpoint fork for changed augmentation')
    return root, {name: Path(name) for name, size in shards}, identity


class RemoteZipDataset(FullZipDataset):
    def __init__(self, active, paths, split, imgsz=512, augment=False, seed=42, connection=None):
        super().__init__(active, paths, split, imgsz, augment, seed)
        require(split in ('train', 'val'), 'Final test is not exposed through the training bridge')
        self.connection = connection
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.prefetched = {}

    def fetch(self, index):
        ident, _, expected = self.rows[index]
        content = self.connection.get(f'/sample/{self.split}/{ident}').content
        require(len(content) >= 4, 'Truncated image response')
        header_size = struct.unpack('!I', content[:4])[0]
        require(0 < header_size <= 4096, 'Invalid image response header')
        header = json.loads(content[4:4 + header_size])
        start = 4 + header_size
        jpeg = content[start:start + header['jpeg_bytes']]
        labels = content[start + header['jpeg_bytes']:]
        require(header['id'] == ident and header['split'] == self.split, 'Image identity mismatch')
        require(header['dataset_sha256'] == self.connection.config['dataset_identity'], 'Dataset response identity differs')
        require(len(jpeg) == header['jpeg_bytes'] and len(labels) == header['label_bytes'], 'Truncated image/label payload')
        require(hashlib.sha256(jpeg).hexdigest() == header['jpeg_sha256'], 'Remote JPEG digest differs')
        require(header.get('source_jpeg_sha256', header['jpeg_sha256']) == expected, 'Original JPEG identity differs')
        require(header.get('preprocess', 'original') == self.connection.preprocess[self.split], 'Transport preprocessing differs')
        require(hashlib.sha256(labels).hexdigest() == header['label_sha256'], 'Remote label digest differs')
        return ident, jpeg, labels.decode('utf8')

    def prefetch(self, indices):
        self.prefetched = dict(zip(indices, self.pool.map(self.fetch, indices)))

    def read_sample(self, index):
        return self.prefetched.pop(index) if index in self.prefetched else self.fetch(index)

    def close(self):
        super().close()
        self.pool.shutdown(wait=True)
