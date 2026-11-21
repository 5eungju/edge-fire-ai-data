"""Pair response JSONs and extract observed inputs, keeping answers out of features."""
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from status_io import write_status

FEATURES = {
    'weather_conditions': ['temperature','rainfall','wind_speed','wind_direction','humidity_percent',
        'atmospheric_pressure','visibility','past_rainfall_7days','surface_temperature','observation_height'],
    'terrain_conditions': ['elevation','slope','slope_aspect','curvature','topographic_position_index',
        'terrain_complexity','hydrological_features'],
    'fuel_conditions': ['fuel_density','surface_fuel_depth','fuel_moisture','fuel_average_age','canopy_height','canopy_coverage'],
}


def canonical_id(name):
    stem = PurePosixPath(name).stem
    match = re.fullmatch(r'([^_]+)_[ST]_(.+)',stem)
    if not match:
        raise ValueError('unknown_filename_pattern')
    return match[1]+'_'+match[2]


def features_from_source(source):
    info = source['source_data_info']
    features = {}
    for section,names in FEATURES.items():
        for name in names:
            value = info.get(section,{}).get(name)
            if value is None or value=='':
                number = None
            elif isinstance(value,bool):
                raise ValueError('boolean_numeric_feature')
            else:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError('nonfinite_feature')
            features[section+'.'+name] = number
    # No target, generated reasoning, final burned area, end time, incident IDs or coordinates.
    return features


def extract(source, label, source_member):
    identifier = canonical_id(source_member)
    event = str(source['raw_data_info']['fire_info']['fire_incident_id'])
    if event != identifier.split('_',1)[0]:
        raise ValueError('incident_id_mismatch')
    if canonical_id(source['source_data_info']['file_name']) != identifier:
        raise ValueError('source_filename_mismatch')
    target = label['labelling_data_info']['countermeasures']['immediate_recommendation']['risk_level']
    if not isinstance(target,str) or not target.strip():
        raise ValueError('missing_risk_annotation')
    inputs = features_from_source(source)
    digest = hashlib.sha256(json.dumps(inputs,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return {'id':identifier,'event_id':event,'features':inputs,'feature_sha256':digest,
            'target_annotation':target.strip(),
            'query_time':source['source_data_info'].get('user_info',{}).get('query_time'),
            'target_meaning':'Dataset-annotated response risk, not measured ignition probability',
            'query':label['labelling_data_info'].get('query',{}).get('query_text')}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(args.output/'response_samples.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,event_id TEXT,official_split TEXT,feature_hash TEXT,target TEXT,record TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS packages(path TEXT PRIMARY KEY,fingerprint TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS rejected(package TEXT,member TEXT,reason TEXT)')
    state = {'pid':os.getpid(),'phase':'extracting_response_inputs','training_ready':False}
    started = time.monotonic()
    packages = [x for x in sorted(args.source.rglob('*.zip')) if x.name.startswith(('TS_','VS_'))]
    for index,source_path in enumerate(packages,1):
        label_prefix = 'TL_' if source_path.name.startswith('TS_') else 'VL_'
        matches = list(args.source.rglob(label_prefix+source_path.name[3:]))
        if len(matches)!=1:
            raise ValueError('Missing or ambiguous paired ZIP: '+source_path.name)
        label_path = matches[0]
        fingerprint = json.dumps([(str(x),x.stat().st_size,x.stat().st_mtime_ns) for x in [source_path,label_path]])
        previous = db.execute('SELECT fingerprint FROM packages WHERE path=?',(str(source_path),)).fetchone()
        if previous:
            if previous[0]!=fingerprint:
                raise ValueError('Source package changed; use a fresh extraction directory')
            continue
        state.update(package_index=index,package_total=len(packages),package=source_path.name)
        write_status(args.output/'status.json',state)
        with zipfile.ZipFile(source_path) as raw,zipfile.ZipFile(label_path) as labels:
            label_map = {}
            for info in labels.infolist():
                if info.filename.lower().endswith('.json'):
                    key = canonical_id(info.filename)
                    if key in label_map:
                        raise ValueError('Duplicate label key within archive')
                    label_map[key] = info
            for number,info in enumerate(raw.infolist(),1):
                if not info.filename.lower().endswith('.json'):
                    continue
                try:
                    key = canonical_id(info.filename)
                    if key not in label_map:
                        raise ValueError('missing_paired_label')
                    source_bytes,label_bytes = raw.read(info),labels.read(label_map[key])
                    record = extract(json.loads(source_bytes.decode('utf-8-sig')),
                                     json.loads(label_bytes.decode('utf-8-sig')),info.filename)
                    record.update(source_archive=str(source_path),source_member=info.filename,
                                  label_member=label_map[key].filename,
                                  source_sha256=hashlib.sha256(source_bytes).hexdigest(),
                                  label_sha256=hashlib.sha256(label_bytes).hexdigest())
                    official = 'train' if source_path.name.startswith('TS_') else 'validation'
                    existing = db.execute('SELECT record FROM samples WHERE id=?',(record['id'],)).fetchone()
                    if existing:
                        raise ValueError('duplicate_sample_id_across_archives')
                    db.execute('INSERT INTO samples VALUES(?,?,?,?,?,?)',(record['id'],record['event_id'],official,
                        record['feature_sha256'],record['target_annotation'],json.dumps(record,ensure_ascii=False)))
                except (ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
                    db.execute('INSERT INTO rejected VALUES(?,?,?)',(source_path.name,info.filename,str(exc)))
                if number%1000==0:
                    state.update(member_index=number,elapsed_seconds=round(time.monotonic()-started,1))
                    write_status(args.output/'status.json',state)
        db.execute('INSERT INTO packages VALUES(?,?)',(str(source_path),fingerprint))
        db.commit()
    state.update(phase='extracted_quality_review_required',
        sample_count=db.execute('SELECT COUNT(*) FROM samples').fetchone()[0],
        event_count=db.execute('SELECT COUNT(DISTINCT event_id) FROM samples').fetchone()[0],
        target_counts=dict(db.execute('SELECT target,COUNT(*) FROM samples GROUP BY target')),
        rejected_count=db.execute('SELECT COUNT(*) FROM rejected').fetchone()[0],
        remaining=['Incident-level split and official-split overlap audit',
                   'Deduplicate identical observed inputs; audit contradictory targets',
                   'Feature missingness and unit review before fitting models'])
    (args.output/'summary.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    write_status(args.output/'status.json',state)
    db.close()
    print(json.dumps(state,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
