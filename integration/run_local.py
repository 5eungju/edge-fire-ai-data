"""Start the C storage worker, backend, and frontend; no AI HTTP service."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx
import psutil

BASE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('EDGEFIRE_RUNTIME_ROOT', str(BASE.parents[1] / 'outputs/edgefire_storage_v1'))).resolve()


def configuration():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'runtime.json'
    if not path.exists():
        path.write_text(json.dumps(dict(token=secrets.token_urlsafe(40), storage_root=str(ROOT),
            vision_model_path=str(ROOT / 'models/UNCONFIGURED.pt'), vision_model_id='unconfigured',
            training_status_path=str(BASE.parents[1] / 'outputs/colab_gpu_stream512_20261122/status.json'),
            processes={}), indent=2), encoding='utf8')
    config = json.loads(path.read_text('utf8'))
    if Path(config['storage_root']).resolve() != ROOT:
        raise ValueError('Runtime storage_root differs from selected C storage directory')
    return path, config


def alive(pid, folder, command):
    try:
        process = psutil.Process(pid)
        return process.is_running() and Path(process.cwd()).resolve() == folder.resolve() and all(part in process.cmdline() for part in command[1:])
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    parser.add_argument('--only', choices=['worker', 'backend', 'frontend'])
    args = parser.parse_args()
    path, config = configuration()
    env = os.environ.copy()
    env.update(LOCAL_API_TOKEN=config['token'], STORAGE_ROOT=str(ROOT),
               VISION_MODEL_PATH=config['vision_model_path'], VISION_MODEL_ID=config['vision_model_id'],
               TRAINING_STATUS_PATH=config['training_status_path'], BACKEND_BASE_URL='http://127.0.0.1:8200',
               FRONTEND_BASE_URL='http://127.0.0.1:3200', NEXT_TELEMETRY_DISABLED='1', PYTHONUTF8='1',
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', YOLO_AUTOINSTALL='false')
    services = dict(
        worker=(BASE / 'edgefire_AI', [sys.executable, '-u', 'storage_worker.py', '--root', str(ROOT),
                                     '--model', config['vision_model_path'], '--model-id', config['vision_model_id']]),
        backend=(BASE / 'edgefire_back', [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8200']),
        frontend=(BASE / 'edgefire_front', ['node', str(BASE / 'edgefire_front/node_modules/next/dist/bin/next'),
                                          'start', '--hostname', '127.0.0.1', '--port', '3200']))
    if args.only:
        services = {args.only: services[args.only]}
    for name, (folder, command) in services.items():
        pid = config.get('processes', {}).get(name, 0)
        running = bool(pid and alive(pid, folder, command))
        if args.action == 'stop' and running:
            process = psutil.Process(pid)
            if name == 'worker':
                (ROOT / 'worker.STOP').write_text('User requested worker shutdown', encoding='utf8')
                try:
                    process.wait(timeout=45)
                except psutil.TimeoutExpired:
                    process.terminate()  # The queue lease will allow later recovery.
            else:
                for child in process.children(recursive=True):
                    child.terminate()
                process.terminate()
            running = False
        if args.action == 'start' and not running:
            if name == 'worker' and not Path(config['vision_model_path']).is_file():
                raise RuntimeError('Prepare an immutable inference snapshot before starting the worker')
            logs = ROOT / 'logs'
            logs.mkdir(exist_ok=True)
            if name == 'worker':
                (ROOT / 'worker.STOP').unlink(missing_ok=True)
            with (logs / (name + '.log')).open('ab') as log:
                process = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            config.setdefault('processes', {})[name] = process.pid
            running = True
        print(name, 'RUNNING' if running else 'STOPPED')
    if args.action != 'status':
        path.write_text(json.dumps(config, indent=2), encoding='utf8')
    if args.action == 'start':
        for name, (folder, command) in services.items():
            for _ in range(60):
                if not alive(config['processes'][name], folder, command):
                    raise RuntimeError(name + ' exited; inspect C logs')
                try:
                    if name == 'worker':
                        sys.path.insert(0, str(BASE / 'edgefire_AI'))
                        from storage_queue import StorageQueue
                        ready = StorageQueue(ROOT).worker_available()
                    else:
                        ready = httpx.get('http://127.0.0.1:' + ('8200/' if name == 'backend' else '3200/'), timeout=3).status_code == 200
                    if ready:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError(name + ' not ready; inspect C logs')
        print('화면: http://127.0.0.1:3200')


if __name__ == '__main__':
    main()
