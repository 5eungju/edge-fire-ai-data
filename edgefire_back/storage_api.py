"""Browser-facing storage routes; AI consumes the SQLite queue independently."""
import io
import json
import os
from pathlib import Path
import secrets
import sys
import time
from datetime import datetime

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'edgefire_AI'))
from storage_queue import StorageQueue

ROOT = Path(os.environ.get('STORAGE_ROOT', './local_storage')).resolve()
QUEUE = StorageQueue(ROOT)
db = QUEUE.db
Image.MAX_IMAGE_PIXELS = 30_000_000


def authorized(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get('LOCAL_API_TOKEN')
    if not expected or not x_api_key or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(401, '로컬 API 인증이 필요합니다.')


router = APIRouter(prefix='/api/v1/storage', dependencies=[Depends(authorized)])


@router.get('/forecast')
def forecast():
    path = Path(__file__).resolve().parents[3] / 'outputs/fire_forecast_202512/spread_estimate.geojson'
    if not path.is_file():
        raise HTTPException(404, '확산 추정 결과가 없습니다.')
    return FileResponse(path, media_type='application/geo+json',
                        headers={'Cache-Control': 'no-store'})


@router.get('/config')
def config():
    with db() as con:
        ids = dict(con.execute('SELECT key,value FROM settings').fetchall())
    return ids | dict(storage_type='local_files_and_sqlite_queue', operational_use=False,
                      worker_available=QUEUE.worker_available(),
                      model_id=os.environ.get('VISION_MODEL_ID', 'unconfigured'),
                      model_status='training_snapshot_not_validated',
                      ai_model_available=Path(os.environ.get('VISION_MODEL_PATH', '__missing__')).is_file())


@router.get('/jobs')
def jobs():
    with db() as con:
        rows = con.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100').fetchall()
    return [dict(row) | {'result': json.loads(row['result']) if row['result'] else None} for row in rows]


@router.get('/jobs/{job_id}')
def job(job_id: str):
    try:
        return QUEUE.get(job_id)
    except KeyError:
        raise HTTPException(404, '분석 기록이 없습니다.')


@router.post('/jobs', status_code=202)
async def upload(image: UploadFile = File(...)):
    raw = await image.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, '이미지는 10MiB 이하로 보내 주세요.')
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            if picture.width * picture.height > 30_000_000 or picture.format not in ['JPEG', 'PNG', 'WEBP']:
                raise ValueError('JPEG/PNG/WEBP, 3천만 픽셀 이하만 지원합니다.')
            if picture.getexif().get(274, 1) != 1:
                raise ValueError('이미지 방향을 바로잡아 저장한 뒤 업로드해 주세요.')
            picture.load()
            mime = Image.MIME[picture.format]
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, str(exc) or '유효하지 않은 이미지') from exc
    return QUEUE.enqueue(raw, mime)


@router.post('/jobs/{job_id}/retry', status_code=202)
def retry(job_id: str):
    if not QUEUE.retry(job_id):
        raise HTTPException(409, '실패한 분석만 재시도할 수 있습니다.')
    return job(job_id)


@router.get('/jobs/{job_id}/image')
def original(job_id: str):
    row = job(job_id)
    return FileResponse(QUEUE.path('objects/' + row['object_id']), media_type=row['mime'],
                        headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/jobs/{job_id}/annotated')
def annotated(job_id: str):
    row = job(job_id)
    if row['status'] != 'COMPLETED' or not row['annotated_path']:
        raise HTTPException(404, '분석 이미지가 아직 없습니다.')
    return FileResponse(QUEUE.path(row['annotated_path']), media_type='image/jpeg')


@router.get('/jobs/{job_id}/result')
def result_file(job_id: str):
    row = job(job_id)
    if row['status'] != 'COMPLETED' or not row['result_path']:
        raise HTTPException(404, '분석 결과가 아직 없습니다.')
    return FileResponse(QUEUE.path(row['result_path']), media_type='application/json')


@router.get('/training-status')
def training_status():
    path = Path(os.environ.get('TRAINING_STATUS_PATH', '__missing__'))
    if not path.is_file():
        return {'available': False}
    try:
        state = json.loads(path.read_text('utf8'))
        phase = state.get('phase', 'unknown')
        age = max(0, time.time() - path.stat().st_mtime)
        if state.get('device', '').startswith('cuda') and state.get('gpu_name'):
            # The PID belongs to Colab Linux, never to this Windows host.
            stale = age > 180
            return dict(available=True, phase='unknown' if stale and phase == 'training' else phase,
                        worker_alive=None, status_source='recent_authenticated_gpu_receipt', stale=stale,
                        epoch=state.get('epoch_index', 0) + 1, epochs=state.get('config', {}).get('epochs'),
                        epoch_cursor=state.get('epoch_cursor'), train_images_per_epoch=state.get('train_images_per_epoch'),
                        gpu_name=state.get('gpu_name'), updated_local=state.get('updated_local'))
        alive = False
        try:
            process = psutil.Process(int(state.get('pid', 0)))
            started = datetime.fromisoformat(state['started_utc']).timestamp()
            alive = process.is_running() and abs(process.create_time() - started) < 10
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, KeyError):
            pass
        if phase not in ['completed', 'failed', 'interrupted', 'paused_with_checkpoint'] and not alive:
            phase = 'stopped'
        return dict(available=True, worker_alive=alive, phase=phase, epoch=state.get('epoch'), epochs=state.get('epochs'))
    except (OSError, ValueError):
        return {'available': False}


@router.get('/telemetry')
def telemetry_history():
    with db() as con:
        rows = con.execute('SELECT * FROM telemetry ORDER BY created DESC LIMIT 100').fetchall()
    return [dict(row) | {'payload': json.loads(row['payload']), 'result': json.loads(row['result'])} for row in rows]
