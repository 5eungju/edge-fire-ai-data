"""Freeze a trusted local training checkpoint for integration inference only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'edgefire_AI'))
from storage_queue import StorageQueue


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--training-status', type=Path, required=True)
    args = parser.parse_args()
    runtime = args.root.resolve() / 'runtime.json'
    if runtime.exists():
        import psutil
        previous = json.loads(runtime.read_text('utf8'))
        pid = previous.get('processes', {}).get('worker')
        if pid:
            try:
                process = psutil.Process(pid)
                if process.is_running() and any(Path(arg).name == 'storage_worker.py' for arg in process.cmdline()):
                    raise RuntimeError('Stop the storage worker before changing its inference snapshot')
            except psutil.NoSuchProcess:
                pass
    import torch
    torch.set_num_threads(1)
    payload = args.source.read_bytes()  # One stable version of an atomically replaced checkpoint.
    sha = hashlib.sha256(payload).hexdigest()
    checkpoint = torch.load(io.BytesIO(payload), map_location='cpu', weights_only=False)
    if not checkpoint.get('full_stream_checkpoint') or len(checkpoint['model'].names) != 6:
        raise ValueError('Expected the trusted six-class full-corpus training checkpoint')
    queue = StorageQueue(args.root)
    model = queue.root / 'models' / ('vision_snapshot_' + sha[:12] + '.pt')
    queue.atomic_bytes(str(model.relative_to(queue.root)), payload)
    provenance = dict(sha256=sha, source_checkpoint=str(args.source.resolve()), captured=time.time(),
        epoch_index=checkpoint['epoch'], epoch_cursor=checkpoint['cursor'], dataset_identity=checkpoint['identity'],
        model_status='training_snapshot_not_validated', operational_use=False)
    queue.atomic_json('models/' + model.stem + '.json', provenance)
    runtime = queue.root / 'runtime.json'
    config = json.loads(runtime.read_text('utf8')) if runtime.exists() else dict(token=secrets.token_urlsafe(40), processes={})
    config.update(storage_root=str(queue.root), vision_model_path=str(model),
                  vision_model_id='training-snapshot-' + sha[:12], training_status_path=str(args.training_status.resolve()))
    queue.atomic_json('runtime.json', config)
    print('Inference snapshot prepared:', model)
    print('SHA256:', sha, 'training cursor:', checkpoint['cursor'], '(not a validated final model)')


if __name__ == '__main__':
    main()
