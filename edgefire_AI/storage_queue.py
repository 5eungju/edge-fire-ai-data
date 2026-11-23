"""Single-host SQLite job queue and atomic file artifacts; no AI HTTP calls."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


class StorageQueue:
    def __init__(self, root):
        self.root = Path(root).resolve()
        for folder in ('objects', 'results', 'models'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            schema = '''
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,node_id TEXT,created REAL,status TEXT,
                    object_id TEXT,mime TEXT,sha256 TEXT,result TEXT,error TEXT);
                CREATE TABLE IF NOT EXISTS telemetry(id TEXT PRIMARY KEY,created REAL,payload TEXT,result TEXT);
                CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY,pid INTEGER,updated REAL,state TEXT,model_id TEXT);
            '''
            for statement in schema.split(';'):
                if statement.strip():
                    db.execute(statement)
            columns = {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
            for name, spec in [('region_id', 'TEXT'), ('attempts', 'INTEGER NOT NULL DEFAULT 0'), ('claim_token', 'TEXT'),
                               ('lease_until', 'REAL'), ('updated', 'REAL'), ('result_path', 'TEXT'), ('annotated_path', 'TEXT')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {spec}')
            db.execute('CREATE INDEX IF NOT EXISTS job_queue_order ON jobs(status,created)')
            for key, prefix in [('project_id', 'PRJ'), ('storage_id', 'STO'), ('owner_id', 'USR'), ('node_id', 'CAM')]:
                db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (key, prefix + '_' + uuid.uuid4().hex))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'metadata.sqlite', timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=20000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Storage path escapes root')
        return path

    def atomic_bytes(self, relative, content):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
        with temp.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)

    def atomic_json(self, relative, content):
        self.atomic_bytes(relative, json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8'))

    def enqueue(self, raw, mime, region_id=None):
        object_id, job_id = uuid.uuid4().hex, 'JOB_' + uuid.uuid4().hex
        self.atomic_bytes('objects/' + object_id, raw)
        now = time.time()
        with self.db() as db:
            node = db.execute("SELECT value FROM settings WHERE key='node_id'").fetchone()[0]
            db.execute('INSERT INTO jobs(id,node_id,created,status,object_id,mime,sha256,updated,region_id) VALUES(?,?,?,?,?,?,?,?,?)',
                       (job_id, node, now, 'PENDING', object_id, mime, hashlib.sha256(raw).hexdigest(), now, region_id))
        return self.get(job_id)

    def get(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def claim(self, lease_seconds=120, max_attempts=3):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET status=CASE WHEN attempts>=? THEN 'FAILED' ELSE 'PENDING' END,"
                       "error='이전 워커 연결이 중단되어 작업을 복구했습니다.',claim_token=NULL,lease_until=NULL,updated=? "
                       "WHERE status='RUNNING' AND COALESCE(lease_until,0)<?", (max_attempts, now, now))
            row = db.execute("SELECT id FROM jobs WHERE status='PENDING' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1,claim_token=?,lease_until=?,updated=?,error=NULL WHERE id=? AND status='PENDING'",
                       (token, now + lease_seconds, now, row['id']))
            job_id = row['id']
        return self.get(job_id)

    def renew(self, job_id, token, lease_seconds=120):
        now = time.time()
        with self.db() as db:
            return db.execute("UPDATE jobs SET lease_until=?,updated=? WHERE id=? AND claim_token=? AND status='RUNNING' AND lease_until>?",
                              (now + lease_seconds, now, job_id, token, now)).rowcount == 1

    def complete(self, job, result, annotated):
        prefix = 'results/' + job['id'] + '/' + job['claim_token']
        result_path, annotated_path = prefix + '/result.json', prefix + '/annotated.jpg'
        payload = dict(result, job_id=job['id'], input_sha256=job['sha256'], completed_at=time.time())
        # Each claim has its own artifact directory, so a stale worker cannot
        # overwrite the winning worker's image or JSON even after lease expiry.
        self.atomic_bytes(annotated_path, annotated)
        self.atomic_json(result_path, payload)
        now = time.time()
        with self.db() as db:
            return db.execute("UPDATE jobs SET status='COMPLETED',result=?,result_path=?,annotated_path=?,error=NULL,updated=?,lease_until=NULL "
                "WHERE id=? AND claim_token=? AND status='RUNNING' AND lease_until>?",
                (json.dumps(payload, ensure_ascii=False, allow_nan=False), result_path, annotated_path, now,
                 job['id'], job['claim_token'], now)).rowcount == 1

    def fail(self, job, error):
        now = time.time()
        with self.db() as db:
            return db.execute("UPDATE jobs SET status='FAILED',error=?,updated=?,lease_until=NULL WHERE id=? AND claim_token=? AND status='RUNNING' AND lease_until>?",
                              (str(error)[:1000], now, job['id'], job['claim_token'], now)).rowcount == 1

    def retry(self, job_id):
        with self.db() as db:
            return db.execute("UPDATE jobs SET status='PENDING',attempts=0,error=NULL,claim_token=NULL,lease_until=NULL,updated=? WHERE id=? AND status='FAILED'",
                              (time.time(), job_id)).rowcount == 1

    def worker_status(self, worker_id, model_id, state='READY'):
        with self.db() as db:
            db.execute('INSERT INTO workers VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,state=excluded.state,model_id=excluded.model_id',
                       (worker_id, os.getpid(), time.time(), state, model_id))

    def worker_available(self):
        with self.db() as db:
            return db.execute("SELECT 1 FROM workers WHERE state='READY' AND updated>? LIMIT 1", (time.time() - 30,)).fetchone() is not None
