"""Recheck capped images against all committed sketches, incrementally, with no candidate cap."""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
import numpy as np
from status_io import write_status


def candidate_indices(hashes,colors,splits,rowids,value,color,split,after):
    xor=hashes^np.uint64(value)
    if hasattr(np,'bitwise_count'):
        distances=np.bitwise_count(xor)
    else:
        lookup=np.array([n.bit_count() for n in range(256)],dtype=np.uint8)
        distances=lookup[xor.view(np.uint8).reshape(-1,8)].sum(axis=1)
    return np.flatnonzero((distances<=4)&(splits!=split)&(rowids>after)&np.all(np.abs(colors-color)<.05,axis=1))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--follow',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    source=sqlite3.connect((args.source/'quality.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
    if source.execute('PRAGMA journal_mode').fetchone()[0].lower()!='wal':
        raise RuntimeError('Live quality DB must use WAL so this reader cannot block its writer')
    db=sqlite3.connect(args.output/'recheck.sqlite')
    db.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS progress(id TEXT PRIMARY KEY,through_rowid INTEGER);
      CREATE TABLE IF NOT EXISTS candidates(a TEXT,b TEXT,distance INTEGER,mse REAL,PRIMARY KEY(a,b));''')
    identity=str(args.source.resolve());old=db.execute("SELECT value FROM settings WHERE key='source'").fetchone()
    if old and old[0]!=identity:raise ValueError('Recheck source changed')
    db.execute("INSERT OR IGNORE INTO settings VALUES('source',?)",(identity,));db.commit()
    state={'pid':os.getpid(),'phase':'starting_uncapped_recheck','training_ready':False,
           'scope':'All committed cross-split sketches for images whose earlier search was capped'}
    write_status(args.output/'status.json',state)
    try:
        while True:
            source.execute('BEGIN')
            metadata=source.execute('SELECT rowid,id,split,dhash,r,g,b FROM sketches ORDER BY rowid').fetchall()
            capped=[r[0] for r in source.execute('SELECT id FROM capped')]
            source.commit()
            snapshot_count=len(metadata)
            if metadata:
                rowids=np.array([r[0] for r in metadata],dtype=np.int64)
                ids=[r[1] for r in metadata];position={identifier:i for i,identifier in enumerate(ids)}
                splits=np.array([r[2] for r in metadata]);hashes=np.array([int(r[3],16) for r in metadata],dtype=np.uint64)
                colors=np.array([r[4:7] for r in metadata],dtype=np.float32);through=int(rowids[-1]);del metadata
                state.update(phase='rechecking_without_candidate_cap',sketches_in_snapshot=snapshot_count,
                    capped_images_in_snapshot=len(capped),images_checked_through_snapshot=0,through_rowid=through)
                write_status(args.output/'status.json',state)
                done=dict(db.execute('SELECT id,through_rowid FROM progress'))
                reviewed=0
                for identifier in capped:
                    prior=done.get(identifier,0)
                    if prior>=through:reviewed+=1;continue
                    i=position[identifier]
                    own=source.execute('SELECT rgb FROM sketches WHERE id=?',(identifier,)).fetchone()[0]
                    pixels=np.frombuffer(own,dtype=np.float32).reshape(16,16,3)
                    indices=candidate_indices(hashes,colors,splits,rowids,int(hashes[i]),colors[i],splits[i],prior)
                    for start in range(0,len(indices),256):
                        batch=[ids[int(n)] for n in indices[start:start+256]]
                        marks=','.join('?' for _ in batch)
                        comparisons=source.execute('SELECT id,dhash,rgb FROM sketches WHERE id IN ('+marks+')',batch).fetchall()
                        for other,dhash,rgb in comparisons:
                            mse=float(np.mean((pixels-np.frombuffer(rgb,dtype=np.float32).reshape(16,16,3))**2))
                            if mse<.006:
                                a,b=sorted((identifier,other))
                                db.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?)',(a,b,(int(hashes[i])^int(dhash,16)).bit_count(),mse))
                    db.execute('INSERT OR REPLACE INTO progress VALUES(?,?)',(identifier,through));db.commit();reviewed+=1
                    if reviewed%25==0 or reviewed==len(capped):
                        state.update(phase='rechecking_without_candidate_cap',sketches_in_snapshot=len(ids),
                            capped_images_in_snapshot=len(capped),images_checked_through_snapshot=reviewed,
                            through_rowid=through,candidate_pairs=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0])
                        write_status(args.output/'status.json',state)
            status=json.loads((args.source/'status.json').read_text(encoding='utf8'))
            final=status.get('full_export_completed',False) and status.get('images_audited',0)==snapshot_count
            state.update(phase='uncapped_recheck_complete_review_required' if final else 'waiting_for_new_sketches',
                full_source_audit_completed=bool(final),candidate_pairs=db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0])
            write_status(args.output/'status.json',state)
            if final or not args.follow:break
            time.sleep(60)
    except BaseException as exc:
        source.rollback();db.rollback();state.update(phase='failed',error=str(exc));write_status(args.output/'status.json',state);raise
    finally:
        source.close();db.close()


if __name__=='__main__':main()
