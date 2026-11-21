"""Supplement the pixel audit with annotation/actual-dimension consistency.

Exports and originals are read only. Issues are review exclusions, not repairs.
This also indexes accepted manifest IDs for reproducible camera-level review.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
import zipfile
from status_io import write_status


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--extra-shards',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--follow',action='store_true')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(args.output/'metadata.sqlite')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA cache_size=-65536')
    db.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS shards(name TEXT PRIMARY KEY,fingerprint TEXT);
      CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY,shard TEXT,camera TEXT,split TEXT,site TEXT,collection TEXT,raw_sha TEXT,width INTEGER,height INTEGER,output_width INTEGER,output_height INTEGER,objects TEXT);
      CREATE TABLE IF NOT EXISTS issues(id TEXT,reason TEXT,details TEXT,PRIMARY KEY(id,reason));''')
    identity=str(args.source.resolve())
    old=db.execute("SELECT value FROM settings WHERE key='source'").fetchone()
    if old and old[0]!=identity: raise ValueError('Metadata audit source changed')
    db.execute("INSERT OR IGNORE INTO settings VALUES('source',?)",(identity,));db.commit()
    state={'pid':os.getpid(),'phase':'checking_metadata','training_ready':False,
           'scope':'All finalized exported annotation bodies versus manifest actual dimensions, camera IDs and output dimensions; source archives unchanged'}
    started=time.monotonic()
    def update(**extra):
        state.update(images_checked=db.execute('SELECT COUNT(*) FROM images').fetchone()[0],
                     shards_checked=db.execute('SELECT COUNT(*) FROM shards').fetchone()[0],
                     issue_records=db.execute('SELECT COUNT(*) FROM issues').fetchone()[0],
                     issue_images=db.execute('SELECT COUNT(DISTINCT id) FROM issues').fetchone()[0],
                     issue_counts=dict(db.execute('SELECT reason,count(*) FROM issues GROUP BY reason')),
                     elapsed_seconds=round(time.monotonic()-started,1),**extra)
        write_status(args.output/'status.json',state)
    def paths():
        result=[p for folder in [args.source/'shards',*args.extra_shards] for p in folder.glob('*.zip')]
        if len({p.name for p in result})!=len(result): raise ValueError('Duplicate metadata shard names')
        return sorted(result)
    update()
    try:
        while True:
            for path in paths():
                fingerprint=json.dumps([path.stat().st_size,path.stat().st_mtime_ns])
                previous=db.execute('SELECT fingerprint FROM shards WHERE name=?',(path.name,)).fetchone()
                if previous:
                    if previous[0]!=fingerprint: raise ValueError('Finalized metadata source shard changed')
                    continue
                with zipfile.ZipFile(path) as archive:
                    records=[json.loads(line) for line in archive.read('shard_manifest.jsonl').decode('utf-8').splitlines()]
                    for row in records:
                        prefix=row['split']+'/'+row['id']
                        data=json.loads(archive.read('annotations_original/'+prefix+'.json'))
                        images=data.get('images',[])
                        problems=[]
                        if len(images)!=1:
                            problems.append(('annotation_image_count',{'count':len(images)}))
                        else:
                            declared=[images[0].get('width'),images[0].get('height')]
                            actual=[row['original_width'],row['original_height']]
                            if declared!=actual: problems.append(('annotation_pixel_dimension_mismatch',{'declared':declared,'actual':actual}))
                        camera=data.get('info',{}).get('camera_id')
                        if camera!=row['group_id']: problems.append(('annotation_camera_mismatch',{'declared':camera,'actual':row['group_id']}))
                        width,height=row['output_width'],row['output_height']
                        ow,oh=row['original_width'],row['original_height']
                        if not 0<width<=1280 or not 0<height<=1280 or abs(width/height-ow/oh)>2/max(1,height):
                            problems.append(('output_size_or_aspect_mismatch',{'original':[ow,oh],'output':[width,height]}))
                        if not row['objects']: problems.append(('empty_export_object_list',{}))
                        db.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (row['id'],path.name,row['group_id'],row['split'],row['site_group'],row['collection'],row['raw_sha256'],ow,oh,width,height,json.dumps(row['objects'],sort_keys=True)))
                        db.executemany('INSERT INTO issues VALUES(?,?,?)',[(row['id'],reason,json.dumps(details)) for reason,details in problems])
                db.execute('INSERT INTO shards VALUES(?,?)',(path.name,fingerprint));db.commit();update(current_shard=path.name,phase='checking_metadata')
            producer=json.loads((args.source/'status.json').read_text(encoding='utf-8'))
            known={r[0] for r in db.execute('SELECT name FROM shards')}
            pending=[p for p in paths() if p.name not in known]
            count=db.execute('SELECT COUNT(*) FROM images').fetchone()[0]
            full=producer['phase']=='export_completed_quality_review_required' and not pending and count==producer['accepted']
            update(phase='metadata_scan_completed_review_required' if full else 'waiting_for_more_shards',
                   full_export_completed=full,producer_phase=producer['phase'])
            if full or not args.follow: break
            time.sleep(10)
    except BaseException as exc:
        db.rollback();update(phase='failed',error=str(exc));raise
    finally:
        db.close()


if __name__=='__main__': main()
