"""Browser-facing storage routes; AI consumes the SQLite queue independently."""
import io
import json
import os
from pathlib import Path
import secrets
import sys
import time
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'edgefire_AI'))
from storage_queue import StorageQueue
from multi_model_storage import model_status, reference_examples, validate_request

ROOT = Path(os.environ.get('STORAGE_ROOT', './local_storage')).resolve()
QUEUE = StorageQueue(ROOT)
ASSESSMENTS = StorageQueue(ROOT / 'assessments')
db = QUEUE.db
Image.MAX_IMAGE_PIXELS = 30_000_000


def authorized(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get('LOCAL_API_TOKEN')
    if not expected or not x_api_key or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(401, '로컬 API 인증이 필요합니다.')


router = APIRouter(prefix='/api/v1/storage', dependencies=[Depends(authorized)])


def air_quality_root():
    return Path(os.environ.get('AIR_QUALITY_ROOT',str(Path(__file__).resolve().parents[3]/'outputs/air_quality_2026_v2'))).resolve()


@router.get('/air-quality/stations')
def air_quality_stations():
    from air_quality_service import stations
    return stations(air_quality_root())


@router.get('/air-quality/series')
def air_quality_series(station: str, end: str | None = None):
    from air_quality_service import series
    try:
        return series(air_quality_root(),station,end)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@router.get('/models')
def models():
    return model_status(ROOT)


@router.get('/model-examples')
def model_examples():
    return reference_examples(ROOT)


@router.post('/assessments', status_code=202)
def create_assessment(payload: dict):
    try:
        validate_request(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if model_status(ROOT)['status'] != 'RESEARCH_MODELS_REGISTERED':
        raise HTTPException(409, '모델 학습·등록이 아직 완료되지 않았습니다.')
    return ASSESSMENTS.enqueue(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8'), 'application/json')


@router.get('/assessments/{job_id}')
def assessment(job_id: str):
    try:
        return ASSESSMENTS.get(job_id)
    except KeyError:
        raise HTTPException(404, '통합 분석 기록이 없습니다.')


@router.get('/forecast')
def forecast():
    path = Path(__file__).resolve().parents[3] / 'outputs/fire_forecast_202512/spread_estimate.geojson'
    if not path.is_file():
        raise HTTPException(404, '확산 추정 결과가 없습니다.')
    return FileResponse(path, media_type='application/geo+json',
                        headers={'Cache-Control': 'no-store'})


@router.get('/forecast/regions')
def forecast_regions():
    from fire_forecast.service import regions
    root = Path(__file__).resolve().parents[3] / 'outputs/fire_forecast_202512'
    return regions(root)


@router.get('/vision-examples')
def vision_examples():
    root = Path(__file__).resolve().parents[3] / 'outputs/image_comparison_demo_v1'
    path = root / 'manifest.json'
    if not path.exists():
        return {'status':'PREPARING','cases':[]}
    data = json.loads(path.read_text(encoding='utf-8'))
    data['cases'] = [{k:v for k,v in case.items() if k not in ['annotations','detections']} for case in data['cases']]
    return dict(data,status='READY')


@router.get('/vision-examples/{case_id}/{variant}')
def vision_example_image(case_id: str, variant: str):
    import re
    if not re.fullmatch(r'[a-f0-9]{16,64}',case_id) or variant not in ['original','ground-truth','prediction']:
        raise HTTPException(404,'비교 이미지가 없습니다.')
    root = Path(__file__).resolve().parents[3] / 'outputs/image_comparison_demo_v1'
    path = root/'manifest.json'
    if not path.exists():raise HTTPException(404,'비교 자료 준비 중입니다.')
    cases = json.loads(path.read_text(encoding='utf-8'))['cases']
    if not any(case['id']==case_id for case in cases):raise HTTPException(404,'비교 이미지가 없습니다.')
    filename = {'original':'original.jpg','ground-truth':'ground_truth.jpg','prediction':'prediction.jpg'}[variant]
    return FileResponse(root/case_id/filename,media_type='image/jpeg',headers={'Cache-Control':'no-store'})


@router.post('/forecast')
def recalculate_forecast(payload: dict):
    from fire_forecast.service import calculate
    root = Path(__file__).resolve().parents[3] / 'outputs/fire_forecast_202512'
    try:
        return calculate(root, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/config')
def config():
    with db() as con:
        ids = dict(con.execute('SELECT key,value FROM settings').fetchall())
    return ids | dict(storage_type='local_files_and_sqlite_queue', operational_use=False,
                      worker_available=QUEUE.worker_available(),
                      model_id=os.environ.get('VISION_MODEL_ID', 'unconfigured'),
                      model_status='training_snapshot_not_validated',
                      ai_model_available=Path(os.environ.get('VISION_MODEL_PATH', '__missing__')).is_file())


from fire_forecast.catalog import REGIONS as REGION_CATALOG
PHOTO_REGIONS = set(REGION_CATALOG)


@router.get('/jobs')
def jobs(region: str | None = None):
    if region is not None and region not in PHOTO_REGIONS | {'unassigned'}:
        raise HTTPException(422, '지원하지 않는 사진 지역입니다.')
    with db() as con:
        if region == 'unassigned':
            rows = con.execute('SELECT * FROM jobs WHERE region_id IS NULL ORDER BY created DESC,id DESC LIMIT 100').fetchall()
        elif region:
            rows = con.execute('SELECT * FROM jobs WHERE region_id=? ORDER BY created DESC,id DESC LIMIT 100',(region,)).fetchall()
        else:
            rows = con.execute('SELECT * FROM jobs ORDER BY created DESC,id DESC LIMIT 100').fetchall()
    return [dict(row) | {'result': json.loads(row['result']) if row['result'] else None} for row in rows]


@router.get('/jobs/{job_id}')
def job(job_id: str):
    try:
        return QUEUE.get(job_id)
    except KeyError:
        raise HTTPException(404, '분석 기록이 없습니다.')


@router.post('/jobs', status_code=202)
async def upload(image: UploadFile = File(...), region_id: str | None = Form(default=None)):
    if region_id is not None and region_id not in PHOTO_REGIONS:
        raise HTTPException(422, '지원하지 않는 사진 지역입니다.')
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
    return QUEUE.enqueue(raw, mime, region_id)


@router.post('/jobs/{job_id}/location')
def assign_photo_region(job_id: str, payload: dict):
    region = payload.get('region_id')
    if not isinstance(region,str) or region not in PHOTO_REGIONS or set(payload) != {'region_id'}:
        raise HTTPException(422, '지원하는 지역 하나를 지정해 주세요.')
    with db() as con:
        if not con.execute('UPDATE jobs SET region_id=? WHERE id=?',(region,job_id)).rowcount:
            raise HTTPException(404, '분석 기록이 없습니다.')
    return job(job_id)


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
