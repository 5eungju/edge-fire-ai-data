"""CPU 학습을 순차 실행하고 검증으로만 선택한 뒤 선정 모델의 시험셋을 평가합니다."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import shutil
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import psutil
from filelock import FileLock
from model_selection import select_candidate
from status_io import write_status
from json_numbers import dumps as numeric_dumps
from training_policy import validate_data_policy, validate_generic_pretrained

BASE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=BASE/'model_comparison_config.json')
    parser.add_argument('--output', type=Path, default=Path('E:/AI_Work/edgefire_spatial_comparison_v1'))
    parser.add_argument('--status', type=Path)
    parser.add_argument('--wait-pid', type=int)
    parser.add_argument('--wait-status', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf8'))
    root = Path(config['dataset_root'])
    data = root/'pilot_yolo_seg/dataset.yaml'
    records = [json.loads(line) for line in (root/'pilot_manifest.jsonl').read_text(encoding='utf8').splitlines()]
    policy = validate_data_policy(data, records)
    if not policy['spatial']:
        raise ValueError('This comparison requires the audited spatial dataset')
    for candidate in config['models']:
        validate_generic_pretrained(candidate['weights'], BASE/'generic_pretrained_manifest.json')
    if args.validate_only:
        print('COMPARISON_PREFLIGHT_PASSED', json.dumps(policy), flush=True)
        return
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output/'model_selection_report.json').exists() and (output/'selected_model_test_metrics.json').exists():
        raise ValueError('Completed comparison already exists; choose a new output directory')
    status_path = args.status or output/'status.json'
    state = {'pid': os.getpid(), 'started_utc': datetime.now(timezone.utc).isoformat(),
             'phase': 'initializing', 'candidate_total': len(config['models']),
             'operationally_validated': False, 'dataset_manifest_sha256': policy['manifest_sha256']}

    def update(**values):
        state.update(values)
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        write_status(status_path, state)

    update()
    with FileLock(str(output/'comparison.lock'), timeout=0):
        try:
            frozen=output/'code_snapshot'
            frozen.mkdir(exist_ok=True)
            frozen_config=output/'frozen_config.json'
            if frozen_config.exists() and json.loads(frozen_config.read_text(encoding='utf8'))!=config:
                raise ValueError('Frozen experiment config differs; use a new output directory')
            frozen_config.write_text(json.dumps(config,indent=2),encoding='utf8')
            frozen_policy=output/'dataset_policy.json'
            if frozen_policy.exists() and json.loads(frozen_policy.read_text(encoding='utf8'))!=policy:
                raise ValueError('Frozen dataset policy differs; use a new output directory')
            frozen_policy.write_text(json.dumps(policy,indent=2),encoding='utf8')
            hashfile=frozen/'sha256.json'
            if not hashfile.exists():
                for name in ['train_vision.py','status_io.py','json_numbers.py','training_policy.py','generic_pretrained_manifest.json','model_selection.py']:
                    shutil.copy2(BASE/name,frozen/name)
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen.iterdir() if p.is_file()}
                hashfile.write_text(json.dumps(hashes,indent=2),encoding='utf8')
            hashes=json.loads(hashfile.read_text(encoding='utf8'))
            for name,digest in hashes.items():
                if hashlib.sha256((frozen/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen experiment code changed')
            spec=importlib.util.spec_from_file_location('frozen_model_selection',frozen/'model_selection.py')
            selector=importlib.util.module_from_spec(spec);spec.loader.exec_module(selector)
            update(code_snapshot_sha256=hashes)
            if args.wait_pid:
                created=None
                try:
                    previous=psutil.Process(args.wait_pid)
                    if not any(Path(arg).name=='train_vision.py' for arg in previous.cmdline()):raise RuntimeError('Wait PID is not the expected training process')
                    created=previous.create_time()
                except psutil.NoSuchProcess:
                    pass
                while created is not None:
                    try:
                        previous = psutil.Process(args.wait_pid)
                        if previous.create_time() != created or not previous.is_running():
                            break
                    except psutil.NoSuchProcess:
                        break
                    progress = {}
                    if args.wait_status:
                        try:
                            saved = json.loads(args.wait_status.read_text(encoding='utf8'))
                            progress = {key: saved.get(key) for key in ['epoch','epochs','completed_epochs']}
                        except (OSError, ValueError):
                            pass
                    update(phase='waiting_for_training', waiting_pid=args.wait_pid, **progress)
                    time.sleep(10)
                if args.wait_status:
                    saved = json.loads(args.wait_status.read_text(encoding='utf8'))
                    if saved['phase'] != 'completed':
                        raise RuntimeError('Previous training stopped without successful completion; review before starting new CPU jobs')
            results = []
            for number, candidate in enumerate(config['models'], 1):
                child_status = output/(candidate['name']+'_status.json')
                if child_status.exists():
                    saved=json.loads(child_status.read_text(encoding='utf8'))
                    expected={'epochs':config['epochs'],'imgsz':config['imgsz'],'batch':config['batch'],'threads':config['threads'],'eval_split':'val','benchmark_validation_count':20,'weights':candidate['weights']}
                    if saved.get('training_script_sha256')!=hashes['train_vision.py'] or saved.get('dataset_manifest_sha256')!=policy['manifest_sha256'] or any(saved.get('config',{}).get(k)!=v for k,v in expected.items()):
                        raise RuntimeError('Existing candidate configuration differs; use a new output directory')
                    if saved['phase']=='completed' and saved['result']['split']=='val':
                        results.append({'name':candidate['name'],'result':saved['result']})
                        continue
                    raise RuntimeError('Partial candidate exists: '+candidate['name']+'; inspect its live process or resume its checkpoint before rerunning. Completed candidates will be reused.')
                command = [sys.executable, '-X', 'utf8', '-u', str(frozen/'train_vision.py'),
                           '--data', str(data), '--project', str(output/'training'), '--name', candidate['name'],
                           '--epochs', str(config['epochs']), '--imgsz', str(config['imgsz']),
                           '--batch', str(config['batch']), '--threads', str(config['threads']),
                           '--weights', candidate['weights'], '--eval-split', 'val',
                           '--benchmark-validation-count', '20', '--status', str(child_status)]
                update(phase='training_candidate',candidate_index=number,candidate_name=candidate['name'],epoch=0,epochs=config['epochs'],completed_epochs=0)
                with (output/(candidate['name']+'.log')).open('ab') as log:
                    child = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    psutil.Process(child.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name=='nt' else 10)
                    while child.poll() is None:
                        progress = {}
                        if child_status.exists():
                            try:
                                saved = json.loads(child_status.read_text(encoding='utf8'))
                                progress = {key: saved.get(key) for key in ['epoch','epochs','completed_epochs']}
                            except (OSError, ValueError):
                                pass
                        update(phase='training_candidate', candidate_index=number, candidate_name=candidate['name'],
                               candidate_pid=child.pid, **progress)
                        time.sleep(5)
                if child.returncode:
                    raise RuntimeError('Candidate failed: '+candidate['name']+'; inspect its log before resuming')
                saved = json.loads(child_status.read_text(encoding='utf8'))
                if saved['phase'] != 'completed' or saved['result']['split'] != 'val':
                    raise RuntimeError('Missing validation-only candidate result')
                results.append({'name': candidate['name'], 'result': saved['result']})
                (output/'candidate_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
            winner, ranked = selector.select_candidate(results)
            report = {'selected_model': winner['name'], 'selected_checkpoint': winner['result']['model'],
                      'selection_rule': '.8 hazard mask F1 + .2 six-class mask F1 at confidence .25; within .01 choose lower single-thread p95 latency',
                      'ranking': ranked, 'test_used_for_selection': False, 'operationally_validated': False}
            (output/'model_selection_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            update(phase='evaluating_winner', selected_model=winner['name'])
            import torch
            from ultralytics import YOLO
            torch.set_num_threads(1)
            evaluator = YOLO(winner['result']['model'])
            metrics = evaluator.val(data=str(data), split='test', imgsz=config['imgsz'], batch=config['batch'],
                                    device='cpu', workers=0, max_det=100, plots=True,
                                    project=str(output/'test_evaluation'), name=winner['name'])
            test = {'selected_model': winner['name'], 'model': winner['result']['model'], 'split': 'test',
                    'metrics': {k:float(v) for k,v in metrics.results_dict.items()}, 'per_class': metrics.summary(),
                    'test_used_for_selection': False, 'operationally_validated': False,
                    'deployment_decision': 'review_required'}
            (output/'selected_model_test_metrics.json').write_text(numeric_dumps(test, ensure_ascii=False, indent=2), encoding='utf8')
            update(phase='completed', selected_model=winner['name'], test_report=str(output/'selected_model_test_metrics.json'))
        except BaseException as exc:
            update(phase='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                   error=str(exc), traceback=traceback.format_exc())
            raise


if __name__ == '__main__':
    main()
