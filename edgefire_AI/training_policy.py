"""공간 분리 실험의 검증 관문. 미검사 데이터나 알려진 배경 중복은 허용하지 않습니다."""
import hashlib
import json
from pathlib import Path
import yaml


def validate_data_policy(data, records):
    data = Path(data).resolve()
    if not any('site_group' in row for row in records):
        return {'spatial': False, 'note': 'Legacy exploratory camera-ID experiment'}
    if not all('site_group' in row for row in records):
        raise ValueError('Mixed spatial and legacy records')
    groups = {split: {row['site_group'] for row in records if row['split'] == split}
              for split in ['train', 'val', 'test']}
    for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
        if groups[a] & groups[b]:
            raise ValueError('Spatial component leakage')
    root = data.parent.parent
    digest = hashlib.sha256((root / 'pilot_manifest.jsonl').read_bytes()).hexdigest()
    validation = json.loads((root / 'validation.json').read_text(encoding='utf8'))
    quality = json.loads((root / 'quality_audit/summary.json').read_text(encoding='utf8'))
    if not validation.get('passed') or validation.get('manifest_sha256') != digest:
        raise ValueError('Spatial file/geometry validation is missing or stale')
    if quality.get('manifest_sha256') != digest:
        raise ValueError('Spatial similarity review is missing or stale')
    if quality['selected_location_name_overlap_count'] or quality['cross_split_visual_similarity_candidates']:
        raise ValueError('Unresolved cross-split location/background similarity')
    spec = yaml.safe_load(data.read_text(encoding='utf8'))
    if Path(spec['path']).resolve() != data.parent:
        raise ValueError('Dataset YAML root does not match audited manifest')
    if any(spec[split] != 'images/' + split for split in ['train', 'val', 'test']):
        raise ValueError('Dataset YAML split paths do not match audited files')
    return {'spatial': True, 'manifest_sha256': digest, 'plan_sha256': validation['plan_sha256']}


def validate_generic_pretrained(weights, registry):
    digest = hashlib.sha256(Path(weights).read_bytes()).hexdigest()
    rows = json.loads(Path(registry).read_text(encoding='utf8'))
    allowed = {row['sha256'] for row in rows if row['pretrained_classes'] == 80}
    if digest not in allowed:
        raise ValueError('Spatial experiment requires a registered generic pretrained checkpoint')
    return digest
