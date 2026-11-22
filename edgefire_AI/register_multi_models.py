"""Publish completed local research artifacts through a hash-checked registry."""
import argparse
import hashlib
import json
from pathlib import Path
from storage_queue import StorageQueue


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--storage-root',type=Path,required=True)
    args=parser.parse_args();root=args.model_root.resolve();storage=args.storage_root.resolve()
    if root.drive.upper()!='C:' or storage.drive.upper()!='C:':raise ValueError('Use C: storage')
    for path in [root/'pipeline_status.json',root/'weighting_status.json']:
        if json.loads(path.read_text(encoding='utf-8'))['phase']!='completed':raise ValueError('Training not completed')
    files=['chemical/catalog.json','chemical/comparison.json','chemical/flash_point.joblib',
        'chemical/heat_of_combustion.joblib','chemical/vapor_pressure.joblib',
        'response_models/comparison.json','response_models/response_hgb.joblib',
        'response_models/response_mlp.pt','response_cases.json']
    sha={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
    StorageQueue(storage).atomic_json('models/multi_model_registry.json',dict(root=str(root),
        version='real-datasets-20261123',sha256=sha,operational_use=False))
    print('Registered',len(sha),'trusted research artifacts')


if __name__=='__main__':main()
