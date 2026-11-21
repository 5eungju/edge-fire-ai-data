"""Incremental read-only shard audit with bounded perceptual candidate searches.

Search caps are explicitly reported; zero flagged pairs never proves universal
absence of duplicate backgrounds. Source archives and exports are not modified.
"""
import argparse
import hashlib
import io
import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
from status_io import write_status


def hash_bands(value):
    widths=(13,13,13,13,12);offset=0
    for band,width in enumerate(widths):
        yield band,(value>>offset)&((1<<width)-1)
        offset+=width


def signature(payload):
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        gray=np.asarray(image.convert('L').resize((9,8)),dtype=np.int16)
        value=sum(int(bit)<<i for i,bit in enumerate((gray[:,1:]>gray[:,:-1]).ravel()))
        tiny=np.asarray(image.convert('RGB').resize((16,16)),dtype=np.float32)/255
    return value,tiny,tiny.mean(axis=(0,1))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--follow',action='store_true')
    parser.add_argument('--candidate-limit',type=int,default=256)
    args=parser.parse_args()
    if args.candidate_limit<1:raise ValueError('Candidate limit must be positive')
    args.output.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(args.output/'quality.sqlite')
    db.executescript('''CREATE TABLE IF NOT EXISTS shards(name TEXT PRIMARY KEY,fingerprint TEXT);
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS sites(site TEXT PRIMARY KEY,split TEXT);
      CREATE TABLE IF NOT EXISTS sketches(id TEXT PRIMARY KEY,split TEXT,site TEXT,dhash TEXT,rgb BLOB,r REAL,g REAL,b REAL,jpeg_sha TEXT);
      CREATE TABLE IF NOT EXISTS bands(band INTEGER,value INTEGER,id TEXT);
      CREATE INDEX IF NOT EXISTS band_lookup ON bands(band,value);
      CREATE INDEX IF NOT EXISTS jpeg_lookup ON sketches(jpeg_sha);
      CREATE TABLE IF NOT EXISTS candidates(a TEXT,b TEXT,distance INTEGER,mse REAL,kind TEXT,PRIMARY KEY(a,b));
      CREATE TABLE IF NOT EXISTS capped(id TEXT PRIMARY KEY);''')
    source_identity=str(args.source.resolve())
    previous_source=db.execute("SELECT value FROM settings WHERE key='source'").fetchone()
    if previous_source and previous_source[0]!=source_identity:raise ValueError('Audit source directory changed')
    db.execute("INSERT OR IGNORE INTO settings VALUES('source',?)",(source_identity,));db.commit()
    state={'pid':os.getpid(),'phase':'auditing_completed_shards','training_ready':False,
           'candidate_limit_per_image':args.candidate_limit,'interpretation':'Review candidates only. Capped searches are incomplete; sources are preserved.'}
    started=time.monotonic()
    def update(**extra):
        state.update(images_audited=db.execute('SELECT COUNT(*) FROM sketches').fetchone()[0],
            shards_audited=db.execute('SELECT COUNT(*) FROM shards').fetchone()[0],
            candidate_pairs=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],
            images_with_capped_search=db.execute('SELECT COUNT(*) FROM capped').fetchone()[0],
            elapsed_seconds=round(time.monotonic()-started,1),**extra)
        write_status(args.output/'status.json',state)
    update()
    try:
        while True:
            for path in sorted((args.source/'shards').glob('*.zip')):
                fingerprint=json.dumps([path.stat().st_size,path.stat().st_mtime_ns])
                previous=db.execute('SELECT fingerprint FROM shards WHERE name=?',(path.name,)).fetchone()
                if previous:
                    if previous[0]!=fingerprint:raise ValueError('Finalized source shard changed')
                    continue
                with zipfile.ZipFile(path) as archive:
                    rows=[json.loads(line) for line in archive.read('shard_manifest.jsonl').decode('utf8').splitlines()]
                    for record in rows:
                        identifier=record['id'];split=record['split'];site=record['site_group']
                        if split not in ('train','val','test'):raise ValueError('Unknown split')
                        old=db.execute('SELECT split FROM sites WHERE site=?',(site,)).fetchone()
                        if old and old[0]!=split:raise ValueError('Site component crosses split boundary')
                        db.execute('INSERT OR IGNORE INTO sites VALUES(?,?)',(site,split))
                        prefix=split+'/'+identifier
                        payload=archive.read('images/'+prefix+'.jpg')
                        # ZIP reading verifies the stored member CRC, including labels and original JSON.
                        text=archive.read('labels/'+prefix+'.txt').decode('utf8')
                        json.loads(archive.read('annotations_original/'+prefix+'.json'))
                        for line in text.splitlines():
                            parts=line.split();cid=int(parts[0]);xy=[float(v) for v in parts[1:]]
                            if cid not in range(6) or len(xy)<6 or len(xy)%2 or not all(np.isfinite(xy)) or any(v<0 or v>1 for v in xy):
                                raise ValueError('Stored label geometry/coordinate schema invalid')
                        value,tiny,color=signature(payload);jpeg_sha=hashlib.sha256(payload).hexdigest()
                        found={};capped=False
                        for band,bucket in hash_bands(value):
                            matches=db.execute('''SELECT s.id,s.dhash,s.rgb FROM bands b JOIN sketches s ON s.id=b.id
                              WHERE b.band=? AND b.value=? AND s.split!=? AND ABS(s.r-?)<.05 AND ABS(s.g-?)<.05 AND ABS(s.b-?)<.05 LIMIT ?''',
                              (band,bucket,split,*[float(c) for c in color],args.candidate_limit+1)).fetchall()
                            if len(matches)>args.candidate_limit:capped=True
                            for other,dhash,rgb in matches:
                                if other in found:continue
                                if len(found)>=args.candidate_limit:capped=True;break
                                found[other]=(dhash,rgb)
                        if capped:db.execute('INSERT OR IGNORE INTO capped VALUES(?)',(identifier,))
                        for other,(dhash,rgb) in found.items():
                            distance=(value^int(dhash,16)).bit_count()
                            if distance>4:continue
                            pixels=np.frombuffer(rgb,dtype=np.float32).reshape(16,16,3)
                            mse=float(np.mean((tiny-pixels)**2))
                            if mse<.006:
                                a,b=sorted((identifier,other))
                                db.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)',(a,b,distance,mse,'perceptual_review'))
                        # Exact output duplicates are checked independently of the perceptual search cap.
                        for (other,) in db.execute('SELECT id FROM sketches WHERE jpeg_sha=? AND split!=?',(jpeg_sha,split)).fetchall():
                            a,b=sorted((identifier,other));db.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?)',(a,b,0,0.,'exact_output_duplicate'))
                        db.execute('INSERT INTO sketches VALUES(?,?,?,?,?,?,?,?,?)',
                            (identifier,split,site,format(value,'016x'),tiny.tobytes(),*[float(c) for c in color],jpeg_sha))
                        db.executemany('INSERT INTO bands VALUES(?,?,?)',[(band,bucket,identifier) for band,bucket in hash_bands(value)])
                    db.execute('INSERT INTO shards VALUES(?,?)',(path.name,fingerprint));db.commit()
                    update(phase='auditing_completed_shards',current_shard=path.name)
                print('AUDITED_SHARD',path.name,len(rows),flush=True)
            producer=json.loads((args.source/'status.json').read_text(encoding='utf8'))
            audited={row[0] for row in db.execute('SELECT name FROM shards')}
            pending=[path.name for path in (args.source/'shards').glob('*.zip') if path.name not in audited]
            count=db.execute('SELECT COUNT(*) FROM sketches').fetchone()[0]
            full=(producer['phase']=='export_completed_quality_review_required' and not pending and count==producer['accepted'])
            update(phase='audit_complete_candidates_review_required' if full else 'waiting_for_more_shards',producer_phase=producer['phase'],full_export_completed=full,pending_finalized_shards=len(pending))
            if full or not args.follow:break
            time.sleep(10)
    except BaseException as exc:
        db.rollback();update(phase='failed',error=str(exc));raise
    finally:
        db.close()


if __name__=='__main__':main()
