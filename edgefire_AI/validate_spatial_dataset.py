"""학습 시작 전 파일·라벨·공간 분리·프레임 간격을 전수 확인합니다."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from PIL import Image
from prepare_spatial_dataset import filename_resolution, validate_geometry
from prepare_vision_dataset import CLASS_NAMES
from plan_spatial_split import conservative_place


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='E:/AI_Work/edgefire_vision_spatial_v3')
    parser.add_argument('--plan', default='E:/AI_Work/edgefire_spatial_plan/spatial_split_plan.json')
    args = parser.parse_args()
    root = Path(args.root)
    summary = json.loads((root / 'preprocess_summary.json').read_text(encoding='utf8'))
    plan_bytes = Path(args.plan).read_bytes()
    assert hashlib.sha256(plan_bytes).hexdigest() == summary['plan_sha256']
    plan = json.loads(plan_bytes)
    manifest_bytes = (root / 'pilot_manifest.jsonl').read_bytes()
    records = [json.loads(line) for line in manifest_bytes.decode('utf8').splitlines()]
    counts, hashes = Counter(), set()
    locations, cameras, components = defaultdict(set), defaultdict(set), defaultdict(set)
    clip_frames, actual_objects = defaultdict(list), Counter()
    pilot = root / 'pilot_yolo_seg'
    for index, row in enumerate(records):
        split, identifier = row['split'], row['id']
        assert re.fullmatch('[a-f0-9]{24}', identifier)
        assert row['raw_sha256'] not in hashes
        hashes.add(row['raw_sha256'])
        counts[split] += 1
        assignment = plan['camera_mapping'][row['group_id']]
        assert assignment == {'split': split, 'group_key': row['site_group']}
        locations[split].add(conservative_place(row['source_member']))
        cameras[split].add(row['group_id'])
        components[split].add(row['site_group'])
        with Image.open(pilot / 'images' / split / (identifier + '.jpg')) as image:
            image.load()
            assert image.size == (row['output_width'], row['output_height'])
            assert max(image.size) <= 1280
        objects, segments = Counter(), []
        for line in (pilot / 'labels' / split / (identifier + '.txt')).read_text().splitlines():
            values = line.split()
            category = int(values[0])
            assert 0 <= category < 6 and len(values) >= 7 and len(values) % 2 == 1
            coords = list(map(float, values[1:]))
            assert all(0 <= value <= 1 for value in coords)
            segments.append((category, list(zip(coords[::2], coords[1::2]))))
            objects[CLASS_NAMES[category]] += 1
        try:
            validate_geometry(segments)
        except ValueError as exc:
            raise ValueError(identifier + " " + split + " " + str(exc)) from exc
        assert dict(objects) == row['objects']
        actual_objects.update(objects)
        original = json.loads((pilot / 'annotations_original' / split / (identifier + '.json')).read_text(encoding='utf8'))
        assert (original['images'][0]['width'], original['images'][0]['height']) == (row['original_width'], row['original_height'])
        assert filename_resolution(Path(original['images'][0]['file_name']).name, PurePosixPath(row['source_member']).name) == row['filename_resolution']
        match = re.search(r'_(\d+)\.\w+$', row['source_member'])
        if match:
            clip_frames[str(PurePosixPath(row['source_member']).parent)].append(int(match[1]))
        if (index + 1) % 500 == 0:
            print('VERIFIED', index + 1, flush=True)
    for grouping in [locations, cameras, components]:
        for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
            assert not grouping[a] & grouping[b]
    for frames in clip_frames.values():
        ordered = sorted(frames)
        assert len(frames) <= 10
        assert all(b - a >= 60 for a, b in zip(ordered, ordered[1:]))
    assert dict(counts) == summary['counts']
    assert dict(actual_objects) == summary['object_counts']
    for split, count in counts.items():
        for folder, extension in [('images', '*.jpg'), ('labels', '*.txt'), ('annotations_original', '*.json')]:
            assert len(list((pilot / folder / split).glob(extension))) == count
    assert (root / 'pilot_manifest.jsonl').read_bytes() == manifest_bytes
    result = {'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'passed': True, 'images_decoded': len(records), 'counts': dict(counts),
              'camera_overlap': 0, 'conservative_place_overlap': 0, 'component_overlap': 0,
              'duplicate_source_sha256': 0, 'serialized_polygon_geometry_valid': True,
              'frame_gap_and_clip_cap_verified': True, 'file_and_manifest_counts_match': True,
              'plan_sha256': summary['plan_sha256']}
    (root / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print('SPATIAL_VALIDATION_COMPLETE', json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
