"""Full reviewed corpus training, CPU compatible and resumable within an epoch.

No extraction, no synthetic data, no replacement of the blocked legacy dataset.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import signal
import time
import traceback
import tempfile

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader
from ultralytics import YOLO
from ultralytics.nn.tasks import SegmentationModel
from ultralytics.models.yolo.segment.val import SegmentationValidator
from ultralytics.utils import DEFAULT_CFG

from full_zip_dataset import CLASSES, FullZipDataset, approve
from training_policy import validate_generic_pretrained
from export_full_portable import approve_portable


def atomic_json(path, value):
    temp = path.with_suffix('.json.tmp')
    with temp.open('w', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def detached_model_copy(model):
    # Criterion holds a reference to the model. Exclude it from checkpoint deepcopy.
    criterion = model.criterion
    model.criterion = None
    try:
        return copy.deepcopy(model).cpu().float()
    finally:
        model.criterion = criterion


def save_checkpoint(path, model, optimizer, epoch, cursor, step, config, identity):
    if shutil.disk_usage(path.parent).free < 2 * 1024**3:
        raise RuntimeError('Less than 2 GiB free: checkpoint write stopped')
    saved_model = detached_model_copy(model)
    state = dict(model=saved_model, optimizer=optimizer.state_dict(), epoch=epoch,
                 cursor=cursor, global_step=step, config=config, identity=identity,
                 torch_rng=torch.get_rng_state(), numpy_rng=np.random.get_state(), random_rng=random.getstate(),
                 cuda_rng=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
                 version='8.4.216', date=time.strftime('%Y-%m-%dT%H:%M:%S'),
                 train_args=vars(model.args), full_stream_checkpoint=True)
    temp = path.with_suffix('.pt.tmp')
    with temp.open('wb') as f:
        torch.save(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def validate(model, active, paths, split, config, run):
    dataset = FullZipDataset(active, paths, split, config['imgsz'])
    loader = DataLoader(dataset, batch_size=config['batch'], num_workers=0, collate_fn=dataset.collate_fn)
    # Existing marker directories satisfy the library's config check; the supplied
    # loader is the sole image source and enforces the admission overlay.
    marker = run / 'validator_config'
    for fold in ('train', 'val', 'test'):
        (marker / fold).mkdir(parents=True, exist_ok=True)
    spec = marker / 'data.yaml'
    spec.write_text(yaml.safe_dump(dict(path=str(marker.resolve()), train='train', val='val', test='test',
                                       names=CLASSES, channels=3)), encoding='utf8')
    validator = SegmentationValidator(dataloader=loader, save_dir=run / f'{split}_epoch_results',
        args=dict(data=str(spec), task='segment', split=split, imgsz=config['imgsz'], batch=config['batch'],
                  device=config.get('device', 'cpu'), workers=0, plots=False, save_json=False, save_txt=False, verbose=False))
    try:
        return {k: float(v) for k, v in validator(model=detached_model_copy(model).eval()).items()}
    finally:
        dataset.close()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--portable-data', type=Path)
    parser.add_argument('--device', default='cpu', choices=['cpu', 'cuda:0'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--weights', default='E:/AI_Work/pretrained/yolo26n-seg.pt')
    parser.add_argument('--imgsz', type=int, default=512)
    parser.add_argument('--batch', type=int, default=2)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--lr', type=float, default=0.0001)
    parser.add_argument('--benchmark-steps', type=int, default=0,
                        help='Explicit timing experiment only, never a completed full run')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    run = args.run.resolve()
    run.mkdir(parents=True, exist_ok=True)
    # Keep a Windows file lock for the entire run, including validation.
    # On Linux keep the lock on the VM filesystem, not Drive FUSE. Different
    # Colab VMs must use different persistent run directories.
    lock_path = run / 'run.lock'
    if os.name != 'nt':
        lock_root = Path(tempfile.gettempdir()) / 'edgefire_training_locks'
        lock_root.mkdir(exist_ok=True)
        lock_path = lock_root / (hashlib.sha256(str(run).encode()).hexdigest() + '.lock')
    lock = lock_path.open('a+b')
    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise RuntimeError('Another process owns this run directory') from exc
    status_path = run / 'status.json'
    config = {k: getattr(args, k) for k in ('weights', 'imgsz', 'batch', 'threads', 'epochs', 'seed', 'lr', 'benchmark_steps')}
    config['device'] = args.device
    files = ['train_full_stream.py', 'full_zip_dataset.py', 'training_policy.py', 'export_full_portable.py',
             'generic_pretrained_manifest.json', 'reviewed_background_links_full_v1.json',
             'reports/full_preparation_quality_20261122.json']
    snapshot = run / 'code_snapshot'
    sources = hashlib.sha256()
    for filename in files:
        source = Path(__file__).parent / filename
        content = source.read_bytes()
        sources.update(filename.encode() + b'\0' + content)
        target = snapshot / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if not args.resume and source.resolve() != target.resolve():
            target.write_bytes(content)
    config['source_sha256'] = sources.hexdigest()
    assert args.imgsz % 32 == 0 and args.batch > 0 and args.epochs > 0
    torch.set_num_threads(args.threads)
    if args.device != 'cpu' and not torch.cuda.is_available():
        raise RuntimeError('CUDA requested but unavailable; no silent CPU fallback')
    device = torch.device(args.device)
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)
    active, paths, identity = approve_portable(args.portable_data) if args.portable_data else approve(args.workspace.resolve())
    atomic_json(run / 'data_policy.json', dict(approved_for_this_loader=True, **identity,
                note='Legacy V4 remains blocked. This identity requires the reviewed admission overlay.'))
    checkpoint = run / 'last.pt'
    if not args.resume and checkpoint.exists():
        raise ValueError('Existing run: use --resume or another output directory')
    if not args.resume:
        validate_generic_pretrained(args.weights, Path(__file__).with_name('generic_pretrained_manifest.json'))
        pretrained = YOLO(args.weights).model
        model = SegmentationModel(cfg=pretrained.yaml, ch=3, nc=6, verbose=False)
        model.load(pretrained)
        del pretrained
        epoch = cursor = step = 0
        atomic_json(run / 'config.json', config)
    else:
        state = torch.load(checkpoint, map_location='cpu', weights_only=False)
        if state['identity'] != identity or state['config'] != config:
            raise ValueError('Resume configuration or reviewed dataset identity differs')
        model = state['model'].float()
        epoch, cursor, step = state['epoch'], state['cursor'], state['global_step']
    model.args = copy.deepcopy(DEFAULT_CFG)
    model.args.epochs = args.epochs
    model.args.imgsz = args.imgsz
    model.names = dict(enumerate(CLASSES))
    model.to(device)
    model.criterion = model.init_criterion()
    for _ in range(epoch):
        if hasattr(model.criterion, 'update'):
            model.criterion.update()
    model.train()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=.0005)
    if args.resume:
        optimizer.load_state_dict(state['optimizer'])
        torch.set_rng_state(state['torch_rng'])
        if args.device != 'cpu' and state.get('cuda_rng') is not None:
            torch.cuda.set_rng_state_all(state['cuda_rng'])
        np.random.set_state(state['numpy_rng'])
        random.setstate(state['random_rng'])
        del state
    dataset = FullZipDataset(active, paths, 'train', args.imgsz, augment=True, seed=args.seed)
    assert len(dataset) == identity['counts']['train']
    stop = [False]
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__(0, True))
    started = last_save = time.monotonic()
    run_images = 0
    base_status = dict(dataset_identity=identity['dataset_sha256'], dataset_scope='all_admitted_training_images',
                       train_images_per_epoch=len(dataset), validation_images=identity['counts']['val'],
                       test_images=identity['counts']['test'], device=str(device), config=config,
                       benchmark_only=bool(args.benchmark_steps), model_promoted=False)
    def status(phase, **extra):
        elapsed = time.monotonic() - started
        rate = run_images / elapsed if elapsed else 0
        atomic_json(status_path, dict(**base_status, phase=phase, pid=os.getpid(), epoch_index=epoch,
                    epoch_cursor=cursor, global_step=step, run_images=run_images, elapsed_seconds=elapsed,
                    images_per_second=rate, estimated_epoch_hours=len(dataset) / rate / 3600 if rate else None,
                    updated_local=time.strftime('%Y-%m-%d %H:%M:%S'), **extra))
    try:
        status('starting')
        while epoch < args.epochs:
            dataset.epoch = epoch
            order = torch.randperm(len(dataset), generator=torch.Generator().manual_seed(args.seed + epoch)).tolist()
            while cursor < len(dataset):
                indices = order[cursor:cursor + args.batch]
                batch = dataset.collate_fn([dataset[i] for i in indices])
                batch = {k: v.to(device) if torch.is_tensor(v) else v for k, v in batch.items()}
                batch['img'] = batch['img'].float().div_(255)
                optimizer.zero_grad(set_to_none=True)
                progress = (epoch + cursor / len(dataset)) / args.epochs
                lr = args.lr * min(1., (step + 1) / 100) * (.1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
                for group in optimizer.param_groups:
                    group['lr'] = lr
                loss, items = model(batch)
                loss = loss.sum()
                if not torch.isfinite(loss):
                    raise FloatingPointError('Nonfinite loss; previous durable checkpoint retained')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 10., error_if_nonfinite=True)
                optimizer.step()
                cursor += len(indices)
                run_images += len(indices)
                step += 1
                status('benchmarking' if args.benchmark_steps else 'training', last_loss=float(loss.detach()), learning_rate=lr)
                if time.monotonic() - last_save >= 120 or step == 5:
                    save_checkpoint(checkpoint, model, optimizer, epoch, cursor, step, config, identity)
                    last_save = time.monotonic()
                if args.benchmark_steps and step >= args.benchmark_steps:
                    status('benchmark_completed', last_loss=float(loss.detach()))
                    return
                if stop[0] or (run / 'STOP').exists():
                    save_checkpoint(checkpoint, model, optimizer, epoch, cursor, step, config, identity)
                    status('paused_with_checkpoint')
                    return
            # Training epoch is durable before starting the complete validation fold.
            save_checkpoint(checkpoint, model, optimizer, epoch, cursor, step, config, identity)
            status('validating_full_holdout')
            metrics = validate(model, active, paths, 'val', config, run)
            atomic_json(run / f'validation_epoch_{epoch + 1}.json', metrics)
            # Test is deliberately not used for checkpoint/model selection.
            epoch += 1
            cursor = 0
            if hasattr(model.criterion, 'update'):
                model.criterion.update()
            model.train()
            save_checkpoint(checkpoint, model, optimizer, epoch, cursor, step, config, identity)
        status('training_and_validation_completed_test_not_evaluated')
    except Exception as exc:
        status('failed_previous_checkpoint_preserved', error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        dataset.close()


if __name__ == '__main__':
    main()
