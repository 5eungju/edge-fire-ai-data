"""Fixed validation-case demonstration; no test access, tuning, or global accuracy claim."""
import argparse
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path
from zipfile import ZipFile
from PIL import Image,ImageDraw
from storage_worker import VisionPredictor
from status_io import write_status

CLASSES=['black_smoke','white_gray_smoke','flame','cloud','fog_haze','chimney_smoke']
COLORS=['#ff5555','#ffaa22','#ff2244','#44aaff','#aa77ff','#33cc88']


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--per-class',type=int,default=2)
    args=p.parse_args();w=args.workspace.resolve();out=w/'outputs/image_comparison_demo_v1'
    out.mkdir(exist_ok=True)
    if (out/'manifest.json').exists():raise FileExistsError('Preserve fixed comparison examples')
    state=dict(pid=os.getpid(),phase='selecting_validation_cases',split='val',not_global_evaluation=True)
    def status(**fields):state.update(fields);write_status(out/'status.json',state)
    status()
    index=w/'outputs/full_portable_20261122/full_dataset.sqlite'
    portable=json.loads((index.parent/'portable_manifest.json').read_text(encoding='utf-8'))
    with index.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=portable['index_sha256']:raise ValueError('Index changed')
    db=sqlite3.connect(index.as_uri()+'?mode=ro',uri=True)
    active=w/'outputs/storage_recovery_20261121/active'
    folders=[Path('E:/AI_Work/edgefire_full_export_v1/shards'),active/'preprocess/shards',Path('E:/AI_Work/edgefire_full_export_recovered_v2/shards')]
    paths={p.name:p for folder in folders for p in folder.glob('*.zip')}
    counts=[0]*6;selected=[];sites=set();handles={}
    # Selection is by annotation coverage before model inference, never by model success.
    for ident,shard,sha,site in db.execute("SELECT id,shard,jpeg_sha,canonical_site FROM images WHERE keep=1 AND split='val' ORDER BY id LIMIT 3000"):
        if site in sites:continue
        path=paths.get(shard)
        if not path:raise FileNotFoundError(shard)
        if shard not in handles:handles[shard]=ZipFile(path)
        archive=handles[shard];label=archive.read(f'labels/val/{ident}.txt').decode()
        annotations=[]
        for line in label.splitlines():
            values=line.split();cid=int(values[0]);coords=list(map(float,values[1:]))
            if not 0<=cid<6 or len(coords)<6 or len(coords)%2 or not all(0<=v<=1 for v in coords):raise ValueError('Invalid label')
            annotations.append(dict(class_id=cid,polygon_normalized=list(zip(coords[::2],coords[1::2]))))
        present=sorted({a['class_id'] for a in annotations});needed=[cid for cid in present if counts[cid]<args.per_class]
        if not needed:continue
        primary=needed[0];counts[primary]+=1;sites.add(site)
        raw=archive.read(f'images/val/{ident}.jpg')
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Image SHA mismatch')
        folder=out/ident;folder.mkdir(exist_ok=True);(folder/'original.jpg').write_bytes(raw)
        with Image.open(io.BytesIO(raw)) as source:
            image=source.convert('RGB');draw=ImageDraw.Draw(image)
            for annotation in annotations:
                points=[(x*image.width,y*image.height) for x,y in annotation['polygon_normalized']]
                draw.line(points+[points[0]],fill=COLORS[annotation['class_id']],width=4)
                draw.text(points[0],CLASSES[annotation['class_id']],fill=COLORS[annotation['class_id']],stroke_width=1,stroke_fill='black')
            image.save(folder/'ground_truth.jpg',quality=95)
        selected.append(dict(id=ident,primary_class=CLASSES[primary],ground_truth_classes=[CLASSES[c] for c in present],
            annotations=annotations,split='val',canonical_site=site,source_shard=shard,jpeg_sha256=sha,
            location_linked=False))
        status(selected=len(selected),coverage=counts)
        if all(count>=args.per_class for count in counts):break
    for handle in handles.values():handle.close()
    if not selected:raise ValueError('No available validation examples')
    runtime=json.loads((w/'outputs/edgefire_storage_v1/runtime.json').read_text())
    predictor=VisionPredictor(Path(runtime['vision_model_path']),runtime['vision_model_id'])
    for i,record in enumerate(selected):
        status(phase='inferring_fixed_validation_cases',completed=i,total=len(selected))
        folder=out/record['id'];result,annotated=predictor((folder/'original.jpg').read_bytes())
        (folder/'prediction.jpg').write_bytes(annotated);write_status(folder/'prediction.json',result)
        record['predicted_classes']=sorted({d['class_name'] for d in result['detections']})
        record['detections']=result['detections'];record['model_id']=result['model_id']
        # Image-level set comparison only; do not present as localization/mask accuracy.
        truth=set(record['ground_truth_classes']);pred=set(record['predicted_classes'])
        record['missed_classes']=sorted(truth-pred);record['extra_classes']=sorted(pred-truth)
    write_status(out/'manifest.json',dict(cases=selected,model_id=predictor.model_id,model_sha256=predictor.sha,
        dataset_identity=portable['identity']['dataset_sha256'],split='val',test_accessed=False,
        selection='First admitted validation IDs covering each class at distinct reviewed sites, before inference',
        coverage={CLASSES[i]:count for i,count in enumerate(counts)},not_global_evaluation=True,
        notice='정답 라벨과 고정 모델의 예측 비교입니다. 소수 사례 시연이며 전체 정확도·실시간 탐지 성능 검증이 아닙니다.'))
    status(phase='completed',completed=len(selected),total=len(selected))
    print('Saved',len(selected),'fixed validation comparisons')


if __name__=='__main__':main()
