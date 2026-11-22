"""Build a compact, reviewed full-corpus index for a different training machine.

Writes metadata only to the requested output directory. Does not copy, extract,
move, or delete any source image ZIP. The image ZIPs must be transferred separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

from full_zip_dataset import CLASSES, approve, readonly, require
from training_policy import validate_generic_pretrained


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_index(db, report):
    digest = hashlib.sha256()
    n = 0
    for ident, keep, split, site in db.execute('SELECT id,keep,split,canonical_site FROM images ORDER BY id'):
        digest.update(f'{ident}|{int(keep)}|{split}|{site}\n'.encode())
        n += 1
    require(n == report['processed_images'], 'Portable image count differs')
    require(digest.hexdigest() == report['admission_sha256'], 'Portable admission mask differs')
    counts = dict(db.execute('SELECT split,count(*) FROM images WHERE keep=1 GROUP BY split'))
    require(counts == report['retained_split_counts'], 'Portable split counts differ')
    corpus = hashlib.sha256()
    rows = list(db.execute('SELECT name,size,sha256 FROM shards ORDER BY name'))
    for name, size, sha in rows:
        require(Path(name).name == name and '/' not in name and '\\' not in name, 'Unsafe shard name')
        corpus.update(f'{name}|{size}|{sha}\n'.encode())
    require(len(rows) == report['finalized_shards'], 'Portable shard count differs')
    require(corpus.hexdigest() == report['export_corpus_sha256'], 'Portable corpus differs')
    require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Portable database failed integrity check')
    return counts


def approve_portable(root, shard_roots=None):
    root = Path(root).resolve()
    manifest = json.loads((root / 'portable_manifest.json').read_text('utf8'))
    source = Path(__file__).parent
    report = json.loads((source / 'reports/full_preparation_quality_20261122.json').read_text('utf8'))
    require(manifest['schema'] == 1, 'Unknown portable schema')
    require(report['automated_scans_completed'] and report['admission_overlay_complete'], 'Review incomplete')
    require(report['known_candidate_pairs_retained_across_folds'] == report['metadata_issue_images'] == 0, 'Review gate failed')
    require(report['integrity_verified_images'] == report['processed_images'], 'Integrity review incomplete')
    require(file_sha(source / 'reviewed_background_links_full_v1.json') == report['reviewed_links_sha256'], 'Review links changed')
    require(file_sha(root / 'full_dataset.sqlite') == manifest['index_sha256'], 'Portable index changed')
    with readonly(root / 'full_dataset.sqlite') as db:
        counts = verify_index(db, report)
        shards = list(db.execute('SELECT name,size FROM shards'))
    identity = {k: report[k] for k in ('inventory_sha256', 'admission_sha256', 'export_corpus_sha256', 'reviewed_links_sha256')}
    identity['classes'] = CLASSES
    identity['dataset_sha256'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    identity['counts'] = counts
    require(identity == manifest['identity'], 'Portable dataset identity differs')
    paths = {}
    for folder in shard_roots or [root / 'shards']:
        for path in Path(folder).rglob('*.zip'):
            require(path.name not in paths, 'Duplicate portable shard')
            paths[path.name] = path
    require(len(paths) == len(shards), 'All 600 reviewed image ZIPs must be transferred before full training')
    for name, size in shards:
        require(name in paths and paths[name].stat().st_size == size, 'Missing/incomplete image ZIP: ' + name)
    return root, paths, identity


def export(workspace, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'full_dataset.sqlite'
    require(not target.exists(), 'Output already exists; use another output directory')
    active, paths, identity = approve(workspace)
    source = Path(__file__).parent
    report = json.loads((source / 'reports/full_preparation_quality_20261122.json').read_text('utf8'))
    temporary = destination / 'full_dataset.sqlite.partial'
    require(not temporary.exists(), 'Partial export exists; preserve it and use another output directory')
    db = sqlite3.connect(temporary, uri=True)
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA cache_size=-65536')
        db.execute('CREATE TABLE images(id TEXT PRIMARY KEY,shard TEXT NOT NULL,split TEXT NOT NULL,'
                   'jpeg_sha TEXT NOT NULL,keep INTEGER NOT NULL CHECK(keep IN(0,1)),canonical_site TEXT NOT NULL)')
        db.execute('CREATE TABLE shards(name TEXT PRIMARY KEY,size INTEGER NOT NULL,sha256 TEXT NOT NULL)')
        for alias, relative in [('metadata', 'metadata/metadata.sqlite'), ('quality', 'quality/quality.sqlite'),
                                ('admission', 'reviewed_full_export_v1/admission.sqlite')]:
            db.execute(f'ATTACH DATABASE ? AS {alias}', ((active / relative).resolve().as_uri() + '?mode=ro',))
        print('Copying reviewed image index; no image ZIPs are being rewritten', flush=True)
        db.execute('INSERT INTO main.images SELECT m.id,m.shard,m.split,q.jpeg_sha,a.keep,a.canonical_site '
                   'FROM metadata.images m JOIN admission.images a ON a.id=m.id '
                   'JOIN quality.sketches q ON q.id=m.id WHERE m.split=a.split')
        with readonly(active / 'integrity/integrity.sqlite') as integrity:
            db.executemany('INSERT INTO main.shards VALUES(?,?,?)', integrity.execute('SELECT name,size,sha256 FROM verified'))
        db.execute('CREATE INDEX image_split_keep ON images(split,keep)')
        db.commit()
        counts = verify_index(db, report)
    finally:
        db.close()
    os.replace(temporary, target)
    files = ['full_zip_dataset.py', 'train_full_stream.py', 'training_policy.py', 'export_full_portable.py',
             'generic_pretrained_manifest.json', 'reviewed_background_links_full_v1.json',
             'reports/full_preparation_quality_20261122.json']
    for name in files:
        output = destination / 'code' / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, output)
    weights = Path('E:/AI_Work/pretrained/yolo26n-seg.pt')
    validate_generic_pretrained(weights, source / 'generic_pretrained_manifest.json')
    (destination / 'pretrained').mkdir(exist_ok=True)
    shutil.copyfile(weights, destination / 'pretrained/yolo26n-seg.pt')
    manifest = dict(schema=1, identity=identity, index_sha256=file_sha(target), index_bytes=target.stat().st_size,
                    counts=counts, image_zip_count=len(paths), image_zip_bytes=report['finalized_export_bytes'],
                    image_zip_transfer_completed=False, contains_images=False,
                    note='Metadata package only. All 600 image ZIPs are required separately; no subset fallback.')
    (destination / 'portable_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf8')
    # Local paths are intentionally kept in the local output, never in GitHub source.
    (destination / 'local_transfer_sources.json').write_text(json.dumps(
        {name: str(path.resolve()) for name, path in sorted(paths.items())}, indent=2), 'utf8')
    print(json.dumps(manifest, indent=2), flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    started = time.monotonic()
    export(arguments.workspace.resolve(), arguments.output)
    print(f'Portable index complete in {time.monotonic() - started:.1f}s', flush=True)
