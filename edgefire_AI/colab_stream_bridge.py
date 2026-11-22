"""Authenticated, bounded training transport; images stay in the original ZIPs.

Bind to loopback only. A temporary HTTPS tunnel may forward this single service.
No directory listing, arbitrary path reads, shell execution, or pickle loading.
"""
import argparse
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import threading
import time
from zipfile import ZipFile
import cv2
import numpy as np

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
import uvicorn

from export_full_portable import file_sha, verify_index
from full_zip_dataset import approve, readonly, require

MAX_CHECKPOINT = 90 * 1024**2
ARTIFACTS = {'last.pt', 'status.json', 'config.json', 'data_policy.json',
             'validation_epoch_1.json', 'validation_epoch_2.json', 'validation_epoch_3.json'}


def training_jpeg(jpeg, max_side):
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Invalid source image')
    h, w = image.shape[:2]
    ratio = min(1., max_side / max(h, w))
    if ratio < 1.:
        image = cv2.resize(image, (round(w * ratio), round(h * ratio)), interpolation=cv2.INTER_LINEAR)
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95,
        cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444])
    if not ok:
        raise ValueError('Transport encoding failed')
    return encoded.tobytes()


def create_app(index, paths, identity, token, run, package, train_max_side=0):
    index, run, package = Path(index), Path(run), Path(package)
    run.mkdir(parents=True, exist_ok=True)
    handles, fingerprints = OrderedDict(), {}
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            for handle in handles.values():
                handle.close()
            handles.clear()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    io_lock, write_lock = threading.Lock(), threading.Lock()
    for name, path in paths.items():
        st = path.stat()
        fingerprints[name] = st.st_size, st.st_mtime_ns
    stats = dict(sample_requests=0, sample_bytes=0, uploads=0, started=time.time())
    preprocess = dict(train=f'resize_long_side_{train_max_side}_jpeg95_444_v1' if train_max_side else 'original', val='original')

    def authorized(value):
        if not hmac.compare_digest(value or '', 'Bearer ' + token):
            raise HTTPException(401, 'Authentication required')

    @app.middleware('http')
    async def authenticate(request: Request, call_next):
        try:
            authorized(request.headers.get('authorization'))
        except HTTPException:
            return Response(status_code=401)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/manifest')
    def manifest():
        return dict(identity=identity, index_sha256=file_sha(index),
                    package_sha256=file_sha(package), stats=stats,
                    transport='authenticated_original_jpeg_and_labels',
                    checkpoint_destination='C: dedicated run directory',
                    preprocess=preprocess,
                    test_access_enabled=False)

    @app.get('/bootstrap.zip')
    def bootstrap():
        return FileResponse(package, media_type='application/zip')

    @app.get('/sample/{split}/{ident}')
    def sample(split: str, ident: str):
        if split not in ('train', 'val') or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', ident):
            raise HTTPException(404)
        with readonly(index) as db:
            row = db.execute('SELECT shard,jpeg_sha FROM images WHERE id=? AND keep=1 AND split=?',
                             (ident, split)).fetchone()
        if row is None:
            raise HTTPException(404)
        name, expected = row
        with io_lock:
            path = paths[name]
            st = path.stat()
            if (st.st_size, st.st_mtime_ns) != fingerprints[name]:
                raise HTTPException(409, 'Source shard changed; revalidate storage')
            if name not in handles:
                handles[name] = ZipFile(path)
                if len(handles) > 24:
                    handles.popitem(last=False)[1].close()
            archive = handles[name]
            handles.move_to_end(name)
            jpeg = archive.read(f'images/{split}/{ident}.jpg')
            label = archive.read(f'labels/{split}/{ident}.txt')
            if hashlib.sha256(jpeg).hexdigest() != expected:
                raise HTTPException(409, 'JPEG changed after review')
            stats['sample_requests'] += 1
            stats['sample_bytes'] += len(jpeg) + len(label)
        if split == 'train' and train_max_side:
            jpeg = training_jpeg(jpeg, train_max_side)
        header = json.dumps(dict(id=ident, split=split, jpeg_bytes=len(jpeg), label_bytes=len(label),
                            source_jpeg_sha256=expected, preprocess=preprocess[split],
                            jpeg_sha256=hashlib.sha256(jpeg).hexdigest(), label_sha256=hashlib.sha256(label).hexdigest(),
                            dataset_sha256=identity['dataset_sha256'])).encode()
        return Response(struct.pack('!I', len(header)) + header + jpeg + label, media_type='application/octet-stream')

    @app.put('/artifact/{name}')
    async def upload(name: str, request: Request):
        if name not in ARTIFACTS:
            raise HTTPException(404)
        limit = MAX_CHECKPOINT if name.endswith('.pt') else 128 * 1024
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(400, 'Invalid length')
        if not 0 < length <= limit:
            raise HTTPException(413, 'Missing or excessive content length')
        if shutil.disk_usage(run).free < length + 2 * 1024**3:
            raise HTTPException(507, 'C: reserve below 2 GiB')
        expected = request.headers.get('x-content-sha256', '')
        if not re.fullmatch('[a-f0-9]{64}', expected):
            raise HTTPException(400, 'SHA256 required')
        temporary = run / (name + '.' + secrets.token_hex(6) + '.partial')
        digest, total = hashlib.sha256(), 0
        # Never unpickle uploaded bytes on the server.
        with temporary.open('xb') as stream:
            async for chunk in request.stream():
                total += len(chunk)
                if total > length:
                    raise HTTPException(413, 'Body exceeds declared length')
                digest.update(chunk)
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if total != length or digest.hexdigest() != expected:
            raise HTTPException(422, 'Incomplete upload or digest mismatch')
        if name.endswith('.json'):
            try:
                value = json.loads(temporary.read_text('utf8'))
                if not isinstance(value, dict):
                    raise ValueError()
                if name == 'status.json' and value.get('dataset_identity') != identity['dataset_sha256']:
                    raise ValueError('Dataset identity mismatch')
                json.dumps(value, allow_nan=False)
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(422, 'Invalid artifact JSON')
        with write_lock:
            os.replace(temporary, run / name)
            stats['uploads'] += 1
            journal = run / 'bridge_receipts.jsonl'
            with journal.open('a', encoding='utf8') as stream:
                stream.write(json.dumps(dict(name=name, bytes=total, sha256=expected, received=time.time())) + '\n')
        return dict(stored=True, bytes=total, sha256=expected)

    @app.get('/artifact/{name}')
    def download_artifact(name: str):
        if name not in ARTIFACTS or not (run / name).is_file():
            raise HTTPException(404)
        return FileResponse(run / name)

    @app.get('/control')
    def control():
        return dict(stop=(run / 'STOP').exists())

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--portable', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--train-max-side', type=int, default=0, choices=[0, 512])
    args = parser.parse_args()
    active, paths, identity = approve(args.workspace)
    credentials = json.loads(args.credentials.read_text('utf8'))
    require(len(credentials['token']) >= 40, 'Strong ephemeral token required')
    manifest = json.loads((args.portable / 'portable_manifest.json').read_text('utf8'))
    index = args.portable / 'full_dataset.sqlite'
    require(file_sha(index) == manifest['index_sha256'], 'Portable index digest differs')
    with readonly(index) as db:
        report = json.loads(Path(__file__).with_name('reports').joinpath('full_preparation_quality_20261122.json').read_text('utf8'))
        verify_index(db, report)
    require(identity == manifest['identity'], 'Bridge dataset identity differs')
    cv2.setNumThreads(1)
    app = create_app(index, paths, identity, credentials['token'], args.run, args.package, args.train_max_side)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
