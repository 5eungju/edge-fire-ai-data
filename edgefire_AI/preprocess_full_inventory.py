"""Resume full-inventory preprocessing into bounded ZIP shards, preserving sources.

Exports are candidates: a separate cross-split similarity audit is still required.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from PIL import Image
from prepare_spatial_dataset import filename_resolution, serialize_segments, validate_geometry
from prepare_vision_dataset import entry_from_row, polygons
from split_zip_reader import ZipReader
from status_io import write_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--index', type=Path, default=Path('E:/AI_Work/edgefire_vision/vision_index.sqlite'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--existing-shards', type=Path, action='append', default=[], help='Read-only prior shard directories when relocating work off a failing volume')
    parser.add_argument('--raw-recovery-map', type=Path, help='Explicit read-only exFAT archive extent map; requires output on a different volume')
    parser.add_argument('--budget-gib', type=float, default=180)
    parser.add_argument('--min-free-gib', type=float, default=50)
    parser.add_argument('--shard-images', type=int, default=1000)
    parser.add_argument('--max-images', type=int, default=0, help='0 means no image-count cap')
    args = parser.parse_args()
    if args.shard_images < 1 or args.budget_gib <= 0:
        raise ValueError('Invalid storage configuration')
    args.output.mkdir(parents=True, exist_ok=True)
    shard_dir = args.output/'shards'
    shard_dir.mkdir(exist_ok=True)
    state = {'pid':os.getpid(),'phase':'waiting_for_full_inventory','training_ready':False,
             'image_count_cap':args.max_images or None,'budget_gib':args.budget_gib,
             'min_free_gib':args.min_free_gib,'scope':'Full source inventory; not pilot quotas'}
    write_status(args.output/'status.json',state)
    deadline = time.monotonic()+7200
    while not args.inventory.is_file():
        if time.monotonic()>deadline:
            raise TimeoutError('Full inventory has not completed')
        time.sleep(10)
    inventory_hash = hashlib.file_digest(args.inventory.open('rb'),'sha256').hexdigest()
    db = sqlite3.connect(args.output/'progress.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS accepted(id TEXT PRIMARY KEY,raw_sha256 TEXT UNIQUE,shard TEXT,split TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS rejected(id TEXT PRIMARY KEY,reason TEXT)')
    previous = db.execute("SELECT value FROM settings WHERE key='inventory_sha256'").fetchone()
    if previous and previous[0]!=inventory_hash:
        raise ValueError('Inventory changed; use another export directory')
    db.execute("INSERT OR IGNORE INTO settings VALUES('inventory_sha256',?)",(inventory_hash,))
    db.commit()
    # Recover a finalized shard if a previous process stopped before the DB commit.
    prior_shards=[path for directory in args.existing_shards for path in directory.glob('*.zip')]
    all_shards=prior_shards+list(shard_dir.glob('*.zip'))
    if len({path.name for path in all_shards})!=len(all_shards):
        raise ValueError('Duplicate shard filenames across existing and active directories')
    known={path.name for path in all_shards}
    missing={row[0] for row in db.execute('SELECT DISTINCT shard FROM accepted')}-known
    if missing:raise ValueError('Previously committed shard files are missing: '+str(sorted(missing)[:10]))
    for path in sorted(all_shards):
        with zipfile.ZipFile(path) as archive:
            rows = [json.loads(line) for line in archive.read('shard_manifest.jsonl').decode('utf8').splitlines()]
        db.executemany('INSERT OR IGNORE INTO accepted VALUES(?,?,?,?)',
                       [(r['id'],r['raw_sha256'],path.name,r['split']) for r in rows])
    db.commit()
    source = sqlite3.connect(args.index.resolve().as_uri()+'?mode=ro',uri=True)
    source.row_factory = sqlite3.Row
    fingerprint = json.loads(source.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0])
    recovery_volume = None
    if args.raw_recovery_map:
        from raw_recovery_reader import open_recovered_readers
        readers, recovery_volume = open_recovered_readers(args.raw_recovery_map, fingerprint, args.output)
        state.update(source_access='read_only_recovered_extents', source_filesystem_restored=False,
                     recovery_map_sha256=hashlib.sha256(args.raw_recovery_map.read_bytes()).hexdigest())
    else:
        for files in fingerprint.values():
            for row in files:
                actual = Path(row['path']).stat()
                if actual.st_size!=row['bytes'] or actual.st_mtime_ns!=row['mtime_ns']:
                    raise ValueError('Source archive changed; repeat integrity review')
        readers = {role:ZipReader(files[-1]['path']) for role,files in fingerprint.items()}
    completed = {row[0] for row in db.execute('SELECT id FROM accepted UNION SELECT id FROM rejected')}
    digests = {row[0] for row in db.execute('SELECT raw_sha256 FROM accepted')}
    rows, archive, temporary, stream = [], None, None, None
    accepted_count = db.execute('SELECT COUNT(*) FROM accepted').fetchone()[0]
    rejected_count = db.execute('SELECT COUNT(*) FROM rejected').fetchone()[0]
    bytes_written = sum(p.stat().st_size for p in shard_dir.iterdir() if p.is_file())
    prior_bytes = sum(p.stat().st_size for p in prior_shards)
    started = time.monotonic()

    def update(phase='preprocessing', **extra):
        state.update(phase=phase,accepted=accepted_count,rejected=rejected_count,
                     staged_in_current_shard=len(rows),export_bytes=bytes_written+prior_bytes,
                     local_export_bytes=bytes_written,prior_export_bytes=prior_bytes,
                     elapsed_seconds=round(time.monotonic()-started,1),
                     inventory_sha256=inventory_hash,**extra)
        write_status(args.output/'status.json',state)

    def finish_shard():
        nonlocal archive, rows, bytes_written
        if archive is None:
            return
        archive.writestr('shard_manifest.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        archive.close()
        destination = temporary.with_suffix('.zip')
        temporary.replace(destination)
        db.executemany('INSERT INTO accepted VALUES(?,?,?,?)',
                       [(r['id'],r['raw_sha256'],destination.name,r['split']) for r in rows])
        db.commit()
        bytes_written += destination.stat().st_size
        rows, archive = [], None
        update()

    try:
        with args.inventory.open(encoding='utf8') as stream:
            for line in stream:
                row = json.loads(line)
                if row['preparation_status']!='pending_pixel_and_label_validation' or row['id'] in completed:
                    continue
                free = shutil.disk_usage(args.output).free
                staged_bytes = temporary.stat().st_size if archive is not None else 0
                if free < args.min_free_gib*1024**3 or bytes_written+staged_bytes >= args.budget_gib*1024**3:
                    finish_shard()
                    update('paused_storage_limit',free_bytes=free)
                    return
                if args.max_images and accepted_count>=args.max_images:
                    finish_shard()
                    update('paused_requested_count')
                    return
                try:
                    image_bytes = readers[row['role']].read(entry_from_row(row))
                    digest = hashlib.sha256(image_bytes).hexdigest()
                    if digest in digests:
                        raise ValueError('exact_duplicate_image')
                    label = source.execute('SELECT * FROM members WHERE role=? AND key=?',(row['label_role'],row['key'])).fetchone()
                    label_bytes = readers[row['label_role']].read(entry_from_row(label),16*1024*1024)
                    data = json.loads(label_bytes)
                    if data.get('info',{}).get('camera_id')!=row['group_id']:
                        raise ValueError('camera_id_mismatch')
                    with Image.open(io.BytesIO(image_bytes)) as image:
                        try:
                            image.load()
                        except OSError as exc:
                            raise ValueError('image_decode_error: '+str(exc)) from exc
                        if image.getexif().get(274,1)!=1:
                            raise ValueError('exif_rotation_requires_review')
                        width,height = image.size
                        segments,classes,clipped = polygons(data,width,height)
                        validate_geometry(segments)
                        resolution = filename_resolution(Path(data['images'][0]['file_name']).name,PurePosixPath(row['name']).name)
                        image = image.convert('RGB')
                        image.thumbnail((1280,1280),Image.Resampling.LANCZOS)
                        encoded = io.BytesIO()
                        image.save(encoded,format='JPEG',quality=90,subsampling=0)
                    record = {'id':row['id'],'source_archive':row['role'],'source_member':row['name'],
                              'raw_sha256':digest,'group_id':row['group_id'],'site_group':row['site_group'],
                              'split':row['split'],'collection':row['collection'],'objects':dict(classes),
                              'original_width':width,'original_height':height,
                              'output_width':image.width,'output_height':image.height,
                              'filename_resolution':resolution,'clipped_boundary_points':clipped}
                    if archive is None:
                        temporary = shard_dir/('shard_'+uuid.uuid4().hex+'.partial')
                        archive = zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED)
                    prefix = row['split']+'/'+row['id']
                    archive.writestr('images/'+prefix+'.jpg',encoded.getvalue())
                    archive.writestr('labels/'+prefix+'.txt',serialize_segments(segments))
                    archive.writestr('annotations_original/'+prefix+'.json',label_bytes)
                    rows.append(record)
                    digests.add(digest)
                    completed.add(row['id'])
                    accepted_count += 1
                    if len(rows)>=args.shard_images:
                        finish_shard()
                except ValueError as exc:
                    db.execute('INSERT OR IGNORE INTO rejected VALUES(?,?)',(row['id'],str(exc)))
                    rejected_count += 1
                    completed.add(row['id'])
                if (accepted_count+rejected_count)%100==0:
                    db.commit()
                    update()
        finish_shard()
        update('export_completed_quality_review_required')
    except BaseException as exc:
        if archive is not None:
            archive.close()  # An incomplete .partial is preserved, never admitted as a finalized shard.
        db.commit()
        update('interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=str(exc))
        raise
    finally:
        for reader in readers.values():
            reader.close()
        if recovery_volume is not None:
            recovery_volume.close()
        source.close()
        db.close()


if __name__=='__main__':
    main()
