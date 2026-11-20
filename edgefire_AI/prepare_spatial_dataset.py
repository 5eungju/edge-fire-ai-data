"""장소·카메라 연결 성분으로 분리하고 검증된 마스크만 추출합니다."""
import argparse
import hashlib
import io
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from PIL import Image
from shapely.geometry import Polygon
from shapely.validation import explain_validity

from prepare_vision_dataset import CLASS_NAMES, entry_from_row, polygons
from split_zip_reader import ZipReader


def filename_resolution(declared, expected):
    if declared == expected:
        return None
    if declared.replace('백색백색회색연기', '백색회색연기') == expected:
        return {'declared': declared, 'resolved': expected, 'rule': 'repeated_white_smoke_token'}
    raise ValueError('unresolved_label_filename')


def validate_geometry(segments):
    for _, points in segments:
        shape = Polygon(points)
        if not shape.is_valid:
            raise ValueError('invalid_polygon_geometry: ' + explain_validity(shape))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', default='E:/AI_Work/edgefire_vision/vision_index.sqlite')
    parser.add_argument('--plan', default='E:/AI_Work/edgefire_spatial_plan/spatial_split_plan.json')
    parser.add_argument('--output', default='E:/AI_Work/edgefire_vision_spatial_v3')
    args = parser.parse_args()
    output = Path(args.output)
    if (output / 'pilot_manifest.jsonl').exists():
        raise ValueError('기존 표본을 보존하려면 새로운 출력 경로를 사용하세요.')
    output.mkdir(parents=True, exist_ok=True)
    pilot = output / 'pilot_yolo_seg'
    for folder in ['images', 'labels', 'annotations_original']:
        for split in ['train', 'val', 'test']:
            (pilot / folder / split).mkdir(parents=True, exist_ok=True)
    plan_bytes = Path(args.plan).read_bytes()
    plan = json.loads(plan_bytes)
    connection = sqlite3.connect('file:' + args.index + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TEMP TABLE spatial_map(camera TEXT PRIMARY KEY,split TEXT,site_group TEXT)')
    connection.executemany('INSERT INTO spatial_map VALUES(?,?,?)',
                           [(camera, row['split'], row['group_key']) for camera, row in plan['camera_mapping'].items()])
    fingerprint = json.loads(connection.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0])
    readers = {role: ZipReader(files[-1]['path']) for role, files in fingerprint.items()}
    records, seen_hashes = [], set()
    clips, clip_frames = Counter(), defaultdict(list)
    reasons, accepted, objects = Counter(), Counter(), Counter()
    quota_results = []
    started = time.monotonic()
    collections = [r[0] for r in connection.execute("SELECT DISTINCT collection FROM members WHERE role IN ('TS','VS') ORDER BY collection")]
    status = {'phase': 'building', 'plan_sha256': hashlib.sha256(plan_bytes).hexdigest()}

    def save_status():
        status.update(counts=dict(accepted), elapsed_seconds=round(time.monotonic() - started, 1), quota_results=quota_results)
        temporary = output / 'status.tmp'
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf8')
        temporary.replace(output / 'status.json')

    save_status()
    with (output / 'rejected.jsonl').open('w', encoding='utf8') as rejected:
        for split, quota in [('train', 300), ('val', 60), ('test', 60)]:
            for collection in collections:
                query = '''SELECT * FROM (
                  SELECT i.*,s.site_group,s.split AS spatial_fold,
                    ROW_NUMBER() OVER(PARTITION BY i.group_id ORDER BY i.rank) AS camera_rank
                  FROM members i JOIN spatial_map s ON s.camera=i.group_id
                  WHERE i.role IN ('TS','VS') AND i.collection=? AND s.split=?
                ) ORDER BY camera_rank,rank LIMIT 20000'''
                success = 0
                for row in connection.execute(query, (collection, split)).fetchall():
                    if success >= quota:
                        break
                    clip = str(PurePosixPath(row['key']).parent)
                    frame_match = re.search(r'_(\d+)$', row['key'])
                    frame = int(frame_match[1]) if frame_match else None
                    if clips[clip] >= 10:
                        reasons['clip_cap'] += 1
                        continue
                    if frame is not None and any(abs(frame - other) < 60 for other in clip_frames[clip]):
                        reasons['frame_gap_under_60'] += 1
                        continue
                    try:
                        label_role = 'TL' if row['role'] == 'TS' else 'VL'
                        label = connection.execute('SELECT * FROM members WHERE role=? AND key=?', (label_role, row['key'])).fetchone()
                        label_bytes = readers[label_role].read(entry_from_row(label), 16*1024*1024)
                        data = json.loads(label_bytes)
                        image_bytes = readers[row['role']].read(entry_from_row(row))
                        digest = hashlib.sha256(image_bytes).hexdigest()
                        if digest in seen_hashes:
                            raise ValueError('exact_duplicate_image')
                        if data.get('info', {}).get('camera_id') != row['group_id']:
                            raise ValueError('camera_id_mismatch')
                        with Image.open(io.BytesIO(image_bytes)) as image:
                            image.load()
                            if image.getexif().get(274, 1) != 1:
                                raise ValueError('exif_rotation_requires_review')
                            width, height = image.size
                            segments, classes, clipped = polygons(data, width, height)
                            validate_geometry(segments)
                            resolution = filename_resolution(Path(data['images'][0]['file_name']).name, PurePosixPath(row['name']).name)
                            image = image.convert('RGB')
                            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
                            identifier = hashlib.sha256((row['role'] + '/' + row['key']).encode()).hexdigest()[:24]
                            target = pilot / 'images' / split / (identifier + '.jpg')
                            image.save(target, quality=90, subsampling=0)
                            text = '\n'.join(str(cid) + ' ' + ' '.join(f'{v:.7f}' for point in pts for v in point) for cid, pts in segments)
                            (pilot / 'labels' / split / (identifier + '.txt')).write_text(text + '\n' if text else '', encoding='utf8')
                            (pilot / 'annotations_original' / split / (identifier + '.json')).write_bytes(label_bytes)
                        records.append({'id': identifier, 'source_archive': row['role'], 'source_member': row['name'],
                                        'raw_sha256': digest, 'group_id': row['group_id'], 'site_group': row['site_group'],
                                        'split': split, 'collection': collection, 'objects': dict(classes),
                                        'original_width': width, 'original_height': height,
                                        'output_width': image.width, 'output_height': image.height,
                                        'filename_resolution': resolution, 'clipped_boundary_points': clipped})
                        seen_hashes.add(digest)
                        clips[clip] += 1
                        if frame is not None:
                            clip_frames[clip].append(frame)
                        objects.update(classes)
                        accepted[split] += 1
                        success += 1
                    except Exception as exc:
                        reasons[str(exc)] += 1
                        rejected.write(json.dumps({'member': row['name'], 'reason': str(exc)}, ensure_ascii=False) + '\n')
                quota_results.append({'split': split, 'collection': collection, 'accepted': success, 'target': quota})
                save_status()
                print('SPATIAL_SAMPLE', split, collection, success, '/', quota, flush=True)
    for key in ['group_id', 'site_group']:
        groups = {split: {r[key] for r in records if r['split'] == split} for split in ['train', 'val', 'test']}
        for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
            assert not groups[a] & groups[b]
    (output / 'pilot_manifest.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records), encoding='utf8')
    (pilot / 'dataset.yaml').write_text('path: ' + pilot.as_posix() + '\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n' + ''.join(f'  {i}: {name}\n' for i, name in enumerate(CLASS_NAMES)), encoding='utf8')
    summary = {'counts': dict(accepted), 'object_counts': dict(objects), 'selection_reasons': dict(reasons),
               'quota_results': quota_results, 'camera_overlap': 0, 'site_group_overlap': 0,
               'geometry_self_intersections_checked': True,
               'resolved_filename_aliases': sum(r['filename_resolution'] is not None for r in records),
               'plan_sha256': status['plan_sha256'],
               'required_initialization': 'Generic pretrained backbone only. Previous wildfire-finetuned models may have seen these evaluation sites.',
               'limitations': ['Conservative name-based location grouping; geographic coordinates not independently verified.',
                               'Collection ratios may be uneven because spatial groups cannot be broken.',
                               'Visual near-duplicate review remains necessary.']}
    (output / 'preprocess_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    status['phase'] = 'completed'
    save_status()
    for reader in readers.values():
        reader.close()
    connection.close()
    print('SPATIAL_DATASET_COMPLETE', json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
