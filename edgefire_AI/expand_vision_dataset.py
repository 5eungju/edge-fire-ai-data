"""시험/검증 표본을 고정하고 카메라 균형·프레임 간격을 적용해 학습 표본 확장."""
from pathlib import Path, PurePosixPath
from collections import Counter,defaultdict
import json,sqlite3,shutil,hashlib,io,re,time
from PIL import Image
from split_zip_reader import ZipReader
from prepare_vision_dataset import entry_from_row,polygons,CLASS_NAMES

def main():
 root=Path('E:/AI_Work/edgefire_vision');out=Path('E:/AI_Work/edgefire_vision_v2');pilot=out/'pilot_yolo_seg'
 if (out/'preprocess_summary.json').exists():raise ValueError('Completed v2 already exists')
 out.mkdir(exist_ok=True)
 for folder in ['images','labels','annotations_original']:
  for split in ['train','val','test']:(pilot/folder/split).mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect('file:'+str(root/'vision_index.sqlite').replace('\\','/')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 fingerprint=json.loads(db.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0]);readers={k:ZipReader(v[-1]['path']) for k,v in fingerprint.items()}
 excluded={(r['archive'],r['member']) for r in map(json.loads,(root/'full_label_audit/issues.jsonl').read_text(encoding='utf8').splitlines())}
 records=[];hashes=set();counts=Counter();objects=Counter();rejects=Counter();clips=Counter();frames=defaultdict(list);started=time.monotonic()
 for row in map(json.loads,(root/'pilot_manifest.jsonl').read_text(encoding='utf8').splitlines()):
  if row['split']=='train':continue
  for folder,suffix in [('images','.jpg'),('labels','.txt'),('annotations_original','.json')]:shutil.copy2(root/'pilot_yolo_seg'/folder/row['split']/(row['id']+suffix),pilot/folder/row['split']/(row['id']+suffix))
  records.append(row);hashes.add(row['raw_sha256']);counts[row['split']]+=1
 collections=[r[0] for r in db.execute("SELECT DISTINCT collection FROM members WHERE role IN ('TS','VS') ORDER BY collection")]
 with (out/'rejected.jsonl').open('w',encoding='utf8') as rejected:
  for collection in collections:
   accepted=0
   query="""SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY group_id ORDER BY rank) AS camera_rank FROM members WHERE role IN ('TS','VS') AND fold='train' AND collection=?) ORDER BY camera_rank,rank LIMIT 18000"""
   for row in db.execute(query,(collection,)).fetchall():
    if accepted>=300:break
    label_role='TL' if row['role']=='TS' else 'VL';label_name=str(PurePosixPath(row['name']).with_suffix('.json'))
    if (label_role,label_name) in excluded:rejects['full_audit_review_required']+=1;continue
    clip=str(PurePosixPath(row['key']).parent);match=re.search(r'_(\d+)$',row['key']);frame=int(match[1]) if match else None
    if clips[clip]>=10:rejects['clip_cap']+=1;continue
    if frame is not None and any(abs(frame-f)<60 for f in frames[clip]):rejects['frame_gap_under_60']+=1;continue
    try:
     label=db.execute('SELECT * FROM members WHERE role=? AND key=?',(label_role,row['key'])).fetchone();label_bytes=readers[label_role].read(entry_from_row(label),16*1024*1024);data=json.loads(label_bytes)
     raw=readers[row['role']].read(entry_from_row(row));digest=hashlib.sha256(raw).hexdigest()
     if digest in hashes:raise ValueError('exact_duplicate')
     with Image.open(io.BytesIO(raw)) as image:
      image.load()
      if image.getexif().get(274,1)!=1:raise ValueError('exif_rotation')
      width,height=image.size;segments,classes,clipped=polygons(data,width,height)
      if Path(data['images'][0]['file_name']).name!=PurePosixPath(row['name']).name:raise ValueError('label_filename_mismatch')
      if data.get('info',{}).get('camera_id') and data['info']['camera_id']!=row['group_id']:raise ValueError('camera_id_mismatch')
      image=image.convert('RGB');image.thumbnail((1280,1280),Image.Resampling.LANCZOS);identifier=hashlib.sha256((row['role']+'/'+row['key']).encode()).hexdigest()[:24]
      target=pilot/'images/train'/(identifier+'.jpg');image.save(target,quality=90,subsampling=0)
      (pilot/'labels/train'/(identifier+'.txt')).write_text('\n'.join(str(cid)+' '+' '.join(f'{v:.7f}' for point in pts for v in point) for cid,pts in segments)+'\n',encoding='utf8')
      (pilot/'annotations_original/train'/(identifier+'.json')).write_bytes(label_bytes)
     record={'id':identifier,'source_archive':row['role'],'source_member':row['name'],'source_crc32':row['crc'],'raw_sha256':digest,'group_id':row['group_id'],'split':'train','collection':collection,'original_width':width,'original_height':height,'output_width':image.width,'output_height':image.height,'objects':dict(classes),'clipped_boundary_points':clipped}
     records.append(record);hashes.add(digest);counts['train']+=1;objects.update(classes);accepted+=1;clips[clip]+=1
     if frame is not None:frames[clip].append(frame)
    except Exception as exc:
     rejects[str(exc)]+=1;rejected.write(json.dumps({'member':row['name'],'reason':str(exc)},ensure_ascii=False)+'\n')
   print('COLLECTION',collection,accepted,'/300',flush=True)
   (out/'build_status.json').write_text(json.dumps({'phase':'building','counts':dict(counts),'collection':collection,'elapsed_seconds':time.monotonic()-started},ensure_ascii=False,indent=2),encoding='utf8')
 groups={split:{r['group_id'] for r in records if r['split']==split} for split in ['train','val','test']}
 for a,b in [('train','val'),('train','test'),('val','test')]:assert not groups[a]&groups[b]
 (out/'pilot_manifest.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf8')
 (pilot/'dataset.yaml').write_text('path: '+pilot.as_posix()+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {name}\n' for i,name in enumerate(CLASS_NAMES)),encoding='utf8')
 summary={'phase':'completed','counts':dict(counts),'train_object_counts':dict(objects),'selection_reasons':dict(rejects),'groups':{k:len(v) for k,v in groups.items()},'group_overlap':0,'validation_and_test_byte_identical_to_v1':True,'excluded_full_audit_labels':len(excluded),'training_clip_cap':10,'minimum_frame_index_gap':60,'frame_gap_is_not_seconds':True,'elapsed_seconds':time.monotonic()-started,'limitations':['No near-duplicate perceptual hash or polygon self-intersection check.','Camera IDs may not uniquely identify physical locations.','Original v1 test has been inspected; v2 comparison is exploratory, not a new blind test.']}
 (out/'preprocess_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8');print('BUILD_COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)
 for reader in readers.values():reader.close()
 db.close()
if __name__=='__main__':main()
