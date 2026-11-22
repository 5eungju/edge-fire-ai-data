"""Read the reviewed full export without extraction or image caches."""
import hashlib
import json
import random
import sqlite3
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

import cv2
import numpy as np
from torch.utils.data import Dataset
from ultralytics.data.augment import Format, LetterBox, RandomFlip, RandomHSV
from ultralytics.data.dataset import YOLODataset
from ultralytics.utils.instance import Instances
from ultralytics.utils.ops import resample_segments, segments2boxes
from zipfile import ZipFile

CLASSES = ['black_smoke', 'white_gray_smoke', 'flame', 'cloud', 'fog_haze', 'chimney_smoke']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def readonly(path):
    return closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True))


def approve(workspace):
    workspace = Path(workspace)
    active = workspace / 'outputs/storage_recovery_20261121/active'
    report = json.loads(Path(__file__).with_name('reports').joinpath('full_preparation_quality_20261122.json').read_text('utf8'))
    require(report['automated_scans_completed'] and report['admission_overlay_complete'], 'Review incomplete')
    require(report['known_candidate_pairs_retained_across_folds'] == 0, 'Known cross-fold conflicts remain')
    require(report['metadata_issue_images'] == 0 and report['all_six_classes_present_in_each_retained_split'], 'Metadata/class gate failed')
    require(report['integrity_verified_images'] == report['processed_images'], 'Integrity review incomplete')
    links = hashlib.sha256(Path(__file__).with_name('reviewed_background_links_full_v1.json').read_bytes()).hexdigest()
    require(links == report['reviewed_links_sha256'], 'Review links changed')
    mask = active / 'reviewed_full_export_v1/admission.sqlite'
    with readonly(mask) as db:
        digest = hashlib.sha256()
        count = 0
        for ident, keep, split, site in db.execute('SELECT id,keep,split,canonical_site FROM images ORDER BY id'):
            digest.update(f'{ident}|{int(keep)}|{split}|{site}\n'.encode())
            count += 1
        require(count == report['processed_images'], 'Admission row count differs')
        require(digest.hexdigest() == report['admission_sha256'], 'Admission mask changed')
        counts = dict(db.execute('SELECT split,count(*) FROM images WHERE keep=1 GROUP BY split'))
        require(counts == report['retained_split_counts'], 'Admitted split counts differ')
    dirs = [Path('E:/AI_Work/edgefire_full_export_v1/shards'), active / 'preprocess/shards',
            Path('E:/AI_Work/edgefire_full_export_recovered_v2/shards')]
    paths = {}
    for folder in dirs:
        for path in folder.glob('*.zip'):
            if path.name in paths:
                raise ValueError('Duplicate shard: ' + path.name)
            paths[path.name] = path
    corpus = hashlib.sha256()
    with readonly(active / 'integrity/integrity.sqlite') as db:
        verified = list(db.execute('SELECT name,size,mtime_ns,sha256 FROM verified ORDER BY name'))
    require(len(paths) == len(verified) == report['finalized_shards'], 'Shard set differs')
    for name, size, mtime, sha in verified:
        st = paths[name].stat()
        require((st.st_size, st.st_mtime_ns) == (size, mtime), 'Changed shard: ' + name)
        corpus.update(f'{name}|{size}|{sha}\n'.encode())
    require(corpus.hexdigest() == report['export_corpus_sha256'], 'Verified corpus digest differs')
    identity = {k: report[k] for k in ('inventory_sha256', 'admission_sha256', 'export_corpus_sha256', 'reviewed_links_sha256')}
    identity['classes'] = CLASSES
    identity['dataset_sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    identity['counts'] = counts
    return active, paths, identity


class FullZipDataset(Dataset):
    collate_fn = staticmethod(YOLODataset.collate_fn)

    def __init__(self, active, paths, split, imgsz=512, augment=False, seed=42):
        self.paths, self.split, self.imgsz, self.augment = paths, split, imgsz, augment
        self.seed, self.epoch, self.handles = seed, 0, OrderedDict()
        self.portable_hashes, self.verified_paths = {}, set()
        portable = Path(active) / 'full_dataset.sqlite'
        if portable.exists():
            with readonly(portable) as db:
                self.rows = [(i, paths[s], sha) for i, s, sha in db.execute(
                    'SELECT id,shard,jpeg_sha FROM images WHERE keep=1 AND split=? ORDER BY id', (split,))]
                self.portable_hashes = {paths[n]: sha for n, sha in db.execute('SELECT name,sha256 FROM shards')}
        else:
            self.rows = self.local_rows(active, paths, split)
        self.format = Format(bbox_format='xywh', normalize=True, return_mask=True,
                             mask_ratio=4, mask_overlap=True, batch_idx=True)

    @staticmethod
    def local_rows(active, paths, split):
        # Sequential scans avoid hundreds of thousands of random page reads into
        # the large similarity database. Only compact IDs and hashes stay in RAM.
        with readonly(Path(active) / 'reviewed_full_export_v1/admission.sqlite') as db:
            allowed = {i for i, in db.execute('SELECT id FROM images WHERE keep=1 AND split=?', (split,))}
        with readonly(Path(active) / 'quality/quality.sqlite') as db:
            hashes = {i: sha for i, sha in db.execute('SELECT id,jpeg_sha FROM sketches') if i in allowed}
        with readonly(Path(active) / 'metadata/metadata.sqlite') as db:
            rows = sorted((i, paths[s], hashes[i]) for i, s, fold in db.execute(
                'SELECT id,shard,split FROM images') if i in allowed and fold == split)
        if len(rows) != len(allowed):
            raise ValueError('Admitted image missing from metadata or quality hashes')
        return rows

    def __len__(self):
        return len(self.rows)

    @property
    def im_files(self):
        # Validator uses commonpath() for metric bookkeeping. Virtual names must
        # share a drive even when physical ZIPs span C and E. No files are created.
        return [self.virtual_file(ident) for ident, _, _ in self.rows]

    def virtual_file(self, ident):
        return str(Path.cwd() / '__zip_stream_virtual__' / self.split / f'{ident}.jpg')

    def __getitem__(self, index):
        ident, path, expected = self.rows[index]
        if path not in self.handles:
            if path in self.portable_hashes and path not in self.verified_paths:
                with path.open('rb') as stream:
                    require(hashlib.file_digest(stream, 'sha256').hexdigest() == self.portable_hashes[path],
                            'Transferred ZIP hash differs: ' + path.name)
                self.verified_paths.add(path)
            self.handles[path] = ZipFile(path)
            if len(self.handles) > 12:
                self.handles.popitem(last=False)[1].close()
        archive = self.handles[path]
        self.handles.move_to_end(path)
        image_bytes = archive.read(f'images/{self.split}/{ident}.jpg')
        if hashlib.sha256(image_bytes).hexdigest() != expected:
            raise ValueError('JPEG changed after review: ' + ident)
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Unreadable JPEG: ' + ident)
        classes, segments = [], []
        for line in archive.read(f'labels/{self.split}/{ident}.txt').decode().splitlines():
            values = np.asarray(line.split(), dtype=np.float32)
            if len(values) < 7 or len(values) % 2 != 1 or not np.isfinite(values).all():
                raise ValueError('Invalid polygon: ' + ident)
            if values[0] != int(values[0]) or not 0 <= values[0] < 6 or (values[1:] < 0).any() or (values[1:] > 1).any():
                raise ValueError('Invalid polygon coordinates: ' + ident)
            classes.append(values[0])
            segments.append(values[1:].reshape(-1, 2))
        boxes = segments2boxes(segments) if segments else np.zeros((0, 4), np.float32)
        n = max(1000, max((len(s) + 1 for s in segments), default=0))
        polygons = np.stack(resample_segments(segments, n=n)) if segments else np.zeros((0, n, 2), np.float32)
        h, w = image.shape[:2]
        sample = dict(img=image, cls=np.asarray(classes, np.float32).reshape(-1, 1),
                      instances=Instances(boxes, polygons, bbox_format='xywh', normalized=True),
                      im_file=self.virtual_file(ident), ori_shape=(h, w),
                      resized_shape=(h, w), ratio_pad=(1., 1.))
        sample = LetterBox((self.imgsz, self.imgsz), scaleup=self.augment)(sample)
        if self.augment:
            random.seed(self.seed + self.epoch * len(self) + index)
            np.random.seed((self.seed + self.epoch * len(self) + index) % 2**32)
            sample = RandomHSV(.015, .4, .3)(sample)
            sample = RandomFlip(.5, direction='horizontal')(sample)
        return self.format(sample)

    def close(self):
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()
