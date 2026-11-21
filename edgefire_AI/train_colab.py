"""GPU-only Colab training with persistent epoch checkpoints; no test-set selection."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--save-dir', type=Path, required=True)
    parser.add_argument('--model', choices=['yolo26n-seg.pt', 'yolo11n-seg.pt'], default='yolo26n-seg.pt')
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    import torch
    import yaml
    from ultralytics import YOLO
    from training_policy import validate_data_policy
    from json_numbers import dumps
    if not torch.cuda.is_available():
        raise RuntimeError('GPU unavailable: select a Colab GPU runtime before training')
    root = args.dataset.resolve()
    data = root/'pilot_yolo_seg/dataset.yaml'
    config = yaml.safe_load(data.read_text(encoding='utf8'))
    config['path'] = str(data.parent)
    data.write_text(yaml.safe_dump(config, sort_keys=False), encoding='utf8')
    manifest = root/'pilot_manifest.jsonl'
    rows = [json.loads(line) for line in manifest.read_text(encoding='utf8').splitlines()]
    policy = validate_data_policy(data, rows)
    groups = {s: {r.get('site_group', r['group_id']) for r in rows if r['split']==s} for s in ['train','val','test']}
    if any(not g for g in groups.values()) or any(groups[a]&groups[b] for a,b in [('train','val'),('train','test'),('val','test')]):
        raise ValueError('Empty split or shared site groups')
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    args.save_dir.mkdir(parents=True, exist_ok=True)
    provenance = args.save_dir/'dataset_provenance.json'
    if provenance.exists():
        previous = json.loads(provenance.read_text())
        if previous['manifest_sha256']!=digest or previous['model']!=args.model:
            raise ValueError('Saved run uses different data/model; use another save directory')
        if not args.resume:
            raise ValueError('Existing run found: use --resume or another save directory')
    provenance.write_text(dumps({'manifest_sha256':digest,'model':args.model,'policy':policy,
        'counts':{s:sum(r['split']==s for r in rows) for s in groups},'gpu':torch.cuda.get_device_name(0)},indent=2))
    checkpoint = args.save_dir/'last.pt'
    if args.resume and not checkpoint.is_file():
        raise FileNotFoundError('No saved last.pt to resume')
    model = YOLO(str(checkpoint) if args.resume else args.model)

    def persist(trainer):
        # Save each epoch to Drive so runtime disconnection does not erase progress.
        for name, source in [('last.pt',trainer.last), ('best.pt',trainer.best), ('results.csv',trainer.csv)]:
            source = Path(source)
            if source.is_file():
                temporary = args.save_dir/(name+'.tmp')
                shutil.copy2(source, temporary)
                temporary.replace(args.save_dir/name)
    model.add_callback('on_model_save', persist)
    model.train(**({'resume':True} if args.resume else dict(data=str(data),epochs=args.epochs,
        imgsz=512,batch=4,device=0,workers=2,cache=False,seed=42,deterministic=True,
        optimizer='AdamW',lr0=.001,weight_decay=.0005,warmup_bias_lr=0.,
        patience=10,save=True,save_period=1,project='/content/edgefire_runs',
        name=args.save_dir.name,exist_ok=False,close_mosaic=2,mosaic=.5)))
    persist(model.trainer)
    metrics = YOLO(str(args.save_dir/'best.pt')).val(data=str(data),split='val',device=0,imgsz=512,batch=4,max_det=100)
    report = {'split':'val','metrics':metrics.results_dict,'per_class':metrics.summary(),
              'test_used_for_selection':False,'operationally_validated':False,'manifest_sha256':digest}
    (args.save_dir/'validation_metrics.json').write_text(dumps(report,indent=2),encoding='utf8')


if __name__ == '__main__':
    main()
