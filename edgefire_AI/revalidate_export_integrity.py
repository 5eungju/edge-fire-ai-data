"""Revalidate every exported ZIP after filesystem recovery, repairing derived data.

Only derived shard ZIPs can be replaced. Damaged copies are renamed and retained,
and replacements are built on C: from CRC/SHA-verified source archive members.
The source archives and filesystem structures are never modified by this tool.
"""
import argparse
import copy
import hashlib
import io
import json
import os
import shutil
from pathlib import Path, PurePosixPath
import sqlite3
import time
import zipfile
import zlib
from PIL import Image
from prepare_vision_dataset import entry_from_row, polygons
from prepare_spatial_dataset import serialize_segments, validate_geometry
from raw_recovery_reader import open_recovered_readers
from status_io import write_status


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--replacement-shards',type=Path,required=True)
    parser.add_argument('--index',type=Path,required=True)
    parser.add_argument('--raw-recovery-map',type=Path,required=True)
    parser.add_argument('--quality',type=Path,required=True)
    parser.add_argument('--metadata',type=Path)
    parser.add_argument('--prioritize-shard',action='append',default=[])
    parser.add_argument('--force-recheck',action='store_true',help='Required for a new filesystem-repair incident, even if sizes/timestamps match')
    parser.add_argument('--min-free-gib',type=float,default=5,help='Reserve free space on the replacement volume')
    args=parser.parse_args()
    source_drive=json.loads(args.raw_recovery_map.read_text(encoding='utf-8'))['source_drive'].upper()
    if args.output.resolve().drive.upper()==source_drive or args.replacement_shards.resolve().drive.upper()==source_drive:
        raise ValueError('Integrity logs and replacements must stay off source volume')
    args.output.mkdir(parents=True,exist_ok=True)
    args.replacement_shards.mkdir(parents=True,exist_ok=True)
    index=sqlite3.connect(args.index.resolve().as_uri()+'?mode=ro',uri=True)
    index.row_factory=sqlite3.Row
    fingerprint=json.loads(index.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0])
    readers,volume=open_recovered_readers(args.raw_recovery_map,fingerprint,args.output)
    quality=sqlite3.connect(args.quality/'quality.sqlite')
    metadata=sqlite3.connect(args.metadata/'metadata.sqlite') if args.metadata else None
    quality.execute('PRAGMA cache_size=-65536')
    progress=sqlite3.connect(args.output/'integrity.sqlite')
    progress.executescript('''CREATE TABLE IF NOT EXISTS verified(name TEXT PRIMARY KEY,path TEXT,size INTEGER,mtime_ns INTEGER,sha256 TEXT,members INTEGER,images INTEGER,repaired_images INTEGER);
      CREATE TABLE IF NOT EXISTS repairs(name TEXT PRIMARY KEY,preserved_path TEXT,replacement_path TEXT,details TEXT);''')
    state={'pid':os.getpid(),'phase':'checking_all_export_crcs','shards_checked':0,
           'members_checked':0,'images_checked':0,'repaired_images':0,'repaired_shards':0,
           'scope':'Fresh ZIP member CRCs and cached JPEG SHA checks after filesystem repair; size/mtime alone is not accepted as proof',
           'training_ready':False}
    started=time.monotonic()
    def update(**extra):
        row=progress.execute('SELECT count(*),coalesce(sum(members),0),coalesce(sum(images),0),coalesce(sum(repaired_images),0) FROM verified').fetchone()
        state.update(shards_checked=row[0],members_checked=row[1],images_checked=row[2],repaired_images=row[3],
                     repaired_shards=progress.execute('SELECT count(*) FROM repairs').fetchone()[0],
                     elapsed_seconds=round(time.monotonic()-started,1),**extra)
        write_status(args.output/'status.json',state)
    def regenerate(record):
        role=record['source_archive']
        key=str(PurePosixPath(record['source_member'].replace('\\','/').lstrip('/')).with_suffix(''))
        image=index.execute('SELECT * FROM members WHERE role=? AND key=?',(role,key)).fetchone()
        label_role='TL' if role=='TS' else 'VL'
        label=index.execute('SELECT * FROM members WHERE role=? AND key=?',(label_role,key)).fetchone()
        if image is None or label is None:raise ValueError('Original source member missing from immutable index')
        payload=readers[role].read(entry_from_row(image))
        if hashlib.sha256(payload).hexdigest()!=record['raw_sha256']:
            raise ValueError('Original source SHA differs from committed shard manifest')
        annotation=readers[label_role].read(entry_from_row(label),16*1024*1024)
        data=json.loads(annotation)
        if data.get('info',{}).get('camera_id')!=record['group_id']:raise ValueError('Original camera ID mismatch')
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if list(image.size)!=[record['original_width'],record['original_height']]:raise ValueError('Original pixel dimensions changed')
            if image.getexif().get(274,1)!=1:raise ValueError('Unexpected source EXIF rotation')
            segments,classes,_=polygons(data,*image.size);validate_geometry(segments)
            if dict(classes)!=record['objects']:raise ValueError('Original annotation classes changed')
            image=image.convert('RGB');image.thumbnail((1280,1280),Image.Resampling.LANCZOS)
            if list(image.size)!=[record['output_width'],record['output_height']]:raise ValueError('Output dimensions changed')
            encoded=io.BytesIO();image.save(encoded,format='JPEG',quality=90,subsampling=0)
        prefix=record['split']+'/'+record['id']
        return {'images/'+prefix+'.jpg':encoded.getvalue(),
                'labels/'+prefix+'.txt':serialize_segments(segments).encode('utf-8'),
                'annotations_original/'+prefix+'.json':annotation}
    update()
    try:
        priority={name:i for i,name in enumerate(args.prioritize_shard)}
        paths=sorted((p for directory in args.directory for p in directory.glob('*.zip')),
                     key=lambda p:(priority.get(p.name,len(priority)),str(p)))
        if len({p.name for p in paths})!=len(paths):raise ValueError('Duplicate shard names before revalidation')
        for path in paths:
            stat=path.stat()
            previous=progress.execute('SELECT path,size,mtime_ns FROM verified WHERE name=?',(path.name,)).fetchone()
            if not args.force_recheck and previous== (str(path.resolve()),stat.st_size,stat.st_mtime_ns):continue
            update(current_shard=path.name,phase='checking_all_export_crcs')
            bad=[]
            with zipfile.ZipFile(path) as archive:
                manifest_payload=archive.read('shard_manifest.jsonl')
                records=[json.loads(line) for line in manifest_payload.decode('utf-8').splitlines()]
                by_id={r['id']:r for r in records}
                if len(by_id)!=len(records) or len(archive.infolist())!=len(records)*3+1:
                    raise ValueError('Unexpected shard manifest/member count')
                cached=dict(quality.execute('SELECT id,jpeg_sha FROM sketches WHERE id IN ('+','.join('?' for _ in records)+')',list(by_id)))
                for member in archive.infolist():
                    try:
                        payload=archive.read(member)
                        if member.filename.startswith('images/'):
                            identifier=PurePosixPath(member.filename).stem
                            if identifier in cached and hashlib.sha256(payload).hexdigest()!=cached[identifier]:
                                raise ValueError('Image SHA differs from pre-recovery quality sketch')
                    except Exception as exc:
                        if member.filename=='shard_manifest.jsonl':raise
                        identifier=PurePosixPath(member.filename).stem
                        if identifier not in by_id:raise ValueError('Damaged member not represented in manifest') from exc
                        bad.append({'name':member.filename,'id':identifier,'error':str(exc)})
                if bad:
                    update(phase='rebuilding_damaged_derived_shard',damaged_members=bad)
                    if shutil.disk_usage(args.replacement_shards).free < stat.st_size+args.min_free_gib*1024**3:
                        raise OSError('Insufficient safe replacement space; damaged shard preserved')
                    replacement=args.replacement_shards/path.name
                    if replacement.resolve()==path.resolve() or replacement.exists():raise ValueError('Replacement would overwrite an existing shard')
                    temporary=replacement.with_suffix('.zip.repair-partial')
                    if temporary.exists():raise FileExistsError('Preserve prior incomplete repair: '+str(temporary))
                    restored={}
                    for identifier in sorted({x['id'] for x in bad}):
                        restored.update(regenerate(by_id[identifier]))
                    with zipfile.ZipFile(temporary,'w') as out:
                        for member in archive.infolist():
                            payload=restored[member.filename] if member.filename in restored else archive.read(member)
                            if (zlib.crc32(payload)&0xffffffff)!=member.CRC:
                                raise ValueError('Reconstructed payload differs from original export CRC: '+member.filename)
                            if member.filename.startswith('images/'):
                                identifier=PurePosixPath(member.filename).stem
                                if identifier in cached and hashlib.sha256(payload).hexdigest()!=cached[identifier]:
                                    raise ValueError('Reconstructed JPEG differs from original quality SHA')
                            out.writestr(copy.copy(member),payload)
                    with zipfile.ZipFile(temporary) as checked:
                        if checked.testzip() is not None:raise ValueError('Repaired ZIP failed CRC validation')
                        if checked.read('shard_manifest.jsonl')!=manifest_payload:raise ValueError('Repair altered committed manifest')
                    with temporary.open('rb+') as flushed:flushed.flush();os.fsync(flushed.fileno())
                    temporary.replace(replacement)
            if bad:
                # All workers must be stopped. Keep damaged bytes and the original
                # filename in the C: replacement; existing ID->shard references hold.
                preserved=path.with_name(path.name+'.corrupt-preserved-20261122')
                if preserved.exists():raise FileExistsError('Preserved damaged shard already exists')
                path.rename(preserved)
                progress.execute('INSERT OR REPLACE INTO repairs VALUES(?,?,?,?)',(path.name,str(preserved.resolve()),str(replacement.resolve()),json.dumps(bad)))
                path=replacement;stat=path.stat()
                # Every image matches cached SHA and every member matches the old
                # CRC; only ZIP structure/timestamps changed. Existing sketches hold.
                quality.execute('UPDATE shards SET fingerprint=? WHERE name=?',(json.dumps([stat.st_size,stat.st_mtime_ns]),path.name));quality.commit()
                if metadata is not None:
                    metadata.execute('UPDATE shards SET fingerprint=? WHERE name=?',(json.dumps([stat.st_size,stat.st_mtime_ns]),path.name));metadata.commit()
            digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
            progress.execute('INSERT OR REPLACE INTO verified VALUES(?,?,?,?,?,?,?,?)',
                (path.name,str(path.resolve()),stat.st_size,stat.st_mtime_ns,digest,len(records)*3+1,len(records),len({x['id'] for x in bad})))
            progress.commit();update()
        update(phase='all_finalized_export_crcs_verified',complete=True)
    except BaseException as exc:
        progress.rollback();quality.rollback();update(phase='failed',error=str(exc));raise
    finally:
        progress.close();quality.close();index.close()
        if metadata is not None:metadata.close()
        for reader in readers.values():reader.close()
        volume.close()


if __name__=='__main__':main()
