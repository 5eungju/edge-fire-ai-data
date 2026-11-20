"""개인 복사본용 SQLite 메타데이터와 로컬 이미지 저장공간."""
import os, io, json, sqlite3, uuid, hashlib, secrets, time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Header, Depends
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
import httpx
from contextlib import contextmanager

ROOT = Path(os.environ.get('STORAGE_ROOT', './local_storage')).resolve()
AI_URL = os.environ.get('AI_BASE_URL', 'http://127.0.0.1:8101')
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / 'objects').mkdir(exist_ok=True)

@contextmanager
def db():
    con = sqlite3.connect(ROOT / 'metadata.sqlite', timeout=15)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

with db() as con:
    con.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,node_id TEXT,created REAL,status TEXT,object_id TEXT,mime TEXT,sha256 TEXT,result TEXT,error TEXT);
    CREATE TABLE IF NOT EXISTS telemetry(id TEXT PRIMARY KEY,created REAL,payload TEXT,result TEXT);''')
    con.execute("UPDATE jobs SET status='FAILED',error='서비스 재시작으로 중단됨. 재시도할 수 있습니다.' WHERE status IN ('PENDING','RUNNING')")
    for key, prefix in [('project_id','PRJ'),('storage_id','STO'),('owner_id','USR'),('node_id','CAM')]:
        con.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (key, prefix+'_'+uuid.uuid4().hex))

def authorized(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get('LOCAL_API_TOKEN')
    if not expected or not x_api_key or not secrets.compare_digest(expected, x_api_key):
        raise HTTPException(401, '로컬 API 인증이 필요합니다.')

router = APIRouter(prefix='/api/v1/storage', dependencies=[Depends(authorized)])

@router.get('/config')
def config():
    with db() as con:
        ids = dict(con.execute('SELECT key,value FROM settings').fetchall())
    return ids | {'storage_type':'local_files_and_sqlite','operational_use':False,
                  'ai_model_available': Path(os.environ.get('VISION_MODEL_PATH','model_vision.pt')).is_file()}

@router.get('/jobs')
def jobs():
    with db() as con:
        rows = con.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 100').fetchall()
    return [dict(r) | {'result': json.loads(r['result']) if r['result'] else None} for r in rows]

@router.get('/jobs/{job_id}')
def job(job_id: str):
    with db() as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, '분석 기록이 없습니다.')
    return dict(row) | {'result': json.loads(row['result']) if row['result'] else None}

def process_job(job_id):
    row = job(job_id)
    with db() as con:
        con.execute("UPDATE jobs SET status='RUNNING',error=NULL WHERE id=?", (job_id,))
    try:
        with (ROOT/'objects'/row['object_id']).open('rb') as stream:
            response = httpx.post(AI_URL+'/api/v1/vision/analyze', files={'image':('image',stream,row['mime'])}, headers={'X-API-Key':os.environ['LOCAL_API_TOKEN']}, timeout=120)
        response.raise_for_status()
        result = response.json()
        with db() as con:
            con.execute("UPDATE jobs SET status='COMPLETED',result=? WHERE id=?", (json.dumps(result,ensure_ascii=False),job_id))
    except Exception as exc:
        with db() as con:
            con.execute("UPDATE jobs SET status='FAILED',error=? WHERE id=?", (str(exc)[:1000],job_id))

@router.post('/jobs', status_code=202)
async def upload(background_tasks: BackgroundTasks, image: UploadFile = File(...)):
    raw = await image.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:
        raise HTTPException(413,'이미지는 10MiB 이하로 보내 주세요.')
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            if picture.width*picture.height>30_000_000 or picture.format not in ['JPEG','PNG','WEBP']:
                raise ValueError('JPEG/PNG/WEBP, 3천만 픽셀 이하만 지원합니다.')
            if picture.getexif().get(274,1)!=1:
                raise ValueError('이미지 방향을 바로잡아 저장한 뒤 업로드해 주세요.')
            picture.load()
            mime=Image.MIME[picture.format]
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError) as exc:
        raise HTTPException(422,str(exc) or '유효하지 않은 이미지') from exc
    identifier='JOB_'+uuid.uuid4().hex; object_id=uuid.uuid4().hex
    (ROOT/'objects'/object_id).write_bytes(raw)
    with db() as con:
        node=con.execute("SELECT value FROM settings WHERE key='node_id'").fetchone()[0]
        con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(identifier,node,time.time(),'PENDING',object_id,mime,hashlib.sha256(raw).hexdigest(),None,None))
    background_tasks.add_task(process_job,identifier)
    return job(identifier)

@router.post('/jobs/{job_id}/retry',status_code=202)
def retry(job_id: str, background_tasks: BackgroundTasks):
    with db() as con:
        changed=con.execute("UPDATE jobs SET status='PENDING' WHERE id=? AND status='FAILED'",(job_id,)).rowcount
    if not changed:
        raise HTTPException(409,'실패한 분석만 재시도할 수 있습니다.')
    background_tasks.add_task(process_job,job_id)
    return job(job_id)

@router.get('/jobs/{job_id}/image')
def original(job_id: str):
    row=job(job_id)
    return FileResponse(ROOT/'objects'/row['object_id'],media_type=row['mime'],headers={'X-Content-Type-Options':'nosniff'})

@router.get('/training-status')
def training_status():
    path=Path(os.environ.get('TRAINING_STATUS_PATH','__missing__'))
    if not path.is_file():return {'available':False}
    try:
        state=json.loads(path.read_text(encoding='utf8'))
        return {'available':True,**{k:state.get(k) for k in ['phase','epoch','epochs','completed_epochs','batches_completed_in_epoch','updated_utc','split_counts','validation_metrics']}}
    except (OSError,ValueError):return {'available':False}
