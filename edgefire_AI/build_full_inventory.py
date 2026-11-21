"""Inventory every source image using frozen site splits, without pilot quotas.

This is a preparation inventory, NOT proof that pixels/labels are training-ready.
Original archives and existing experiments are read-only.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from status_io import write_status


def classify(record, camera_mapping, failed_members):
    if (record['role'], record['key']) in failed_members:
        return 'excluded_archive_corruption', None
    if not record.get('label_member'):
        return 'excluded_missing_label', None
    location = camera_mapping.get(record['group_id'])
    if not location:
        return 'excluded_unmapped_camera', None
    if location['split'] not in ('train', 'val', 'test'):
        raise ValueError('Unknown split in frozen plan')
    return 'pending_pixel_and_label_validation', location


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--index', type=Path, default=Path('E:/AI_Work/edgefire_vision/vision_index.sqlite'))
    p.add_argument('--plan', type=Path, default=Path('E:/AI_Work/edgefire_spatial_plan_v4/spatial_split_plan.json'))
    p.add_argument('--integrity', type=Path, default=Path('E:/AI_Work/archive_integrity/progress.sqlite'))
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output/'full_source_inventory.jsonl'
    if destination.exists():
        raise FileExistsError('Preserve completed inventory; choose another output directory')
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    mapping = plan['camera_mapping']
    # A component must remain entirely within one split, including unused cameras.
    folds = {}
    for row in mapping.values():
        previous = folds.setdefault(row['group_key'], row['split'])
        if previous != row['split']:
            raise ValueError('Site component crosses split boundary')
    source = sqlite3.connect(args.index.resolve().as_uri()+'?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    integrity = sqlite3.connect(args.integrity.resolve().as_uri()+'?mode=ro', uri=True)
    failed = set(integrity.execute('SELECT role,key FROM failures'))
    counts, splits, collections = Counter(), Counter(), Counter()
    state = {'pid':os.getpid(), 'phase':'building_full_inventory',
             'scope':'All TS/VS source image entries; no pilot quotas',
             'plan_sha256':hashlib.sha256(plan_bytes).hexdigest(),
             'training_ready':False}
    query = '''SELECT i.*,l.name AS label_member,
        CASE WHEN i.role='TS' THEN 'TL' ELSE 'VL' END AS label_role
        FROM members i LEFT JOIN members l ON l.key=i.key AND
        l.role=CASE WHEN i.role='TS' THEN 'TL' ELSE 'VL' END
        WHERE i.role IN ('TS','VS') ORDER BY i.role,i.disk,i.offset'''
    pending = destination.with_suffix('.jsonl.partial')
    with pending.open('w', encoding='utf8') as stream:
        for number, row in enumerate(source.execute(query), 1):
            record = dict(row)
            disposition, location = classify(record, mapping, failed)
            record.update(id=hashlib.sha256((record['role']+'/'+record['key']).encode()).hexdigest()[:24],
                          preparation_status=disposition)
            if location:
                record.update(split=location['split'],site_group=location['group_key'])
                splits[location['split']] += 1
                collections[record['collection']] += 1
            counts[disposition] += 1
            stream.write(json.dumps(record, ensure_ascii=False)+'\n')
            if number % 10000 == 0:
                state.update(scanned=number,counts=dict(counts),split_counts=dict(splits))
                write_status(args.output/'status.json',state)
    pending.replace(destination)
    with destination.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    fingerprint = json.loads(source.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0])
    state.update(phase='completed',scanned=sum(counts.values()),counts=dict(counts),
                 split_counts=dict(splits),collection_counts=dict(collections),
                 manifest_sha256=digest,manifest_bytes=destination.stat().st_size,
                 original_archive_fingerprint=fingerprint,
                 next_required=['Decode every included image and verify label geometry',
                                'Global exact/near-duplicate review',
                                'Storage-bounded, resumable training exports',
                                'Regenerate quality reports before GPU training'])
    (args.output/'summary.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    write_status(args.output/'status.json',state)
    integrity.close()
    source.close()
    print(json.dumps({k:state[k] for k in ['phase','scanned','counts','split_counts','training_ready']}),flush=True)


if __name__ == '__main__':
    main()
