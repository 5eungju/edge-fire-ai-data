"""대용량 원본을 보존하고 전체 목록 대조 및 그룹 분리 소규모 YOLO 분할 자료를 만듭니다."""
from pathlib import Path,PurePosixPath
from collections import Counter,defaultdict
import argparse,sqlite3,json,hashlib,re,io,math,time
from PIL import Image,ImageDraw
from split_zip_reader import ZipReader,Entry

CLASS_NAMES=['black_smoke','white_gray_smoke','flame','cloud','fog_haze','chimney_smoke']
EXPECTED_NAMES={1:'흑색연기',2:'백색/회색연기',3:'화염',4:'구름',5:'안개/연무',6:'굴뚝연기'}
def fold(group):
 value=int(hashlib.sha256(('edgefire42:'+group).encode()).hexdigest()[:8],16)%100
 return 'train' if value<80 else 'val' if value<90 else 'test'
def camera_group(name):
 ids=re.findall(r'(?<![A-Z0-9])([A-Z]{2}\d{6})(?!\d)',name)
 return ids[0] if ids else 'path:'+str(PurePosixPath(name).parent)
def entry_from_row(row):return Entry(row['name'],row['disk'],row['offset'],row['compressed'],row['uncompressed'],row['method'],row['crc'],row['flags'])
def polygons(data,width,height):
 images=data.get('images',[])
 if len(images)!=1:raise ValueError('multiple_or_missing_image_records')
 if (images[0]['width'],images[0]['height'])!=(width,height):raise ValueError('image_label_dimension_mismatch')
 categories={int(c['id']):c['name'] for c in data['categories']}
 if categories!=EXPECTED_NAMES:raise ValueError('unexpected_category_map')
 lines=[];classes=Counter();clipped=0
 for a in data.get('annotations',[]):
  if a.get('image_id')!=images[0]['id']:raise ValueError('annotation_image_id_mismatch')
  if a.get('iscrowd',0):raise ValueError('crowd_mask_requires_review')
  seg=a.get('segmentation')
  if not isinstance(seg,list) or len(seg)!=1:raise ValueError('multipart_or_rle_mask_requires_review')
  coords=seg[0]
  if not isinstance(coords,list) or len(coords)<6 or len(coords)%2:raise ValueError('invalid_polygon_length')
  pts=[]
  for x,y in zip(coords[::2],coords[1::2]):
   if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in [x,y]):raise ValueError('invalid_polygon_number')
   if x<-.5 or y<-.5 or x>width+.5 or y>height+.5:raise ValueError('polygon_out_of_bounds')
   clipped+=int(x<0 or y<0 or x>width or y>height)
   point=(min(max(x,0),width)/width,min(max(y,0),height)/height)
   if not pts or pts[-1]!=point:pts.append(point)
  if len(pts)>1 and pts[0]==pts[-1]:pts.pop()
  if len(set(pts))<3:raise ValueError('degenerate_polygon')
  area=abs(sum(pts[i][0]*pts[(i+1)%len(pts)][1]-pts[(i+1)%len(pts)][0]*pts[i][1] for i in range(len(pts))))/2
  if area<=0:raise ValueError('zero_area_polygon')
  cid=int(a['category_id'])-1
  if not 0<=cid<6:raise ValueError('unknown_category_id')
  lines.append((cid,pts));classes[CLASS_NAMES[cid]]+=1
 return lines,classes,clipped

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--data-root',default='E:/AI_Data');parser.add_argument('--output',default='E:/AI_Work/edgefire_vision');parser.add_argument('--pilot-count',type=int,default=1800);parser.add_argument('--max-side',type=int,default=1280)
 args=parser.parse_args();source=next(Path(args.data_root).glob('265.*')).resolve();out=Path(args.output).resolve()
 if out==source or source in out.parents:raise ValueError('Output must be outside original archive directory')
 if (out/'pilot_manifest.jsonl').exists():raise ValueError('Pilot output already exists; choose a new output directory to preserve prior results')
 if args.pilot_count<30 or args.max_side<320:raise ValueError('Invalid pilot configuration')
 out.mkdir(parents=True,exist_ok=True);readers={name:ZipReader(next(source.rglob(name+'.zip'))) for name in ['TS','TL','VS','VL']}
 fingerprint={name:[{'path':str(p),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in reader.parts] for name,reader in readers.items()}
 db=sqlite3.connect(out/'vision_index.sqlite');db.row_factory=sqlite3.Row
 db.executescript('CREATE TABLE IF NOT EXISTS members(role TEXT,key TEXT,name TEXT,disk INT,offset INT,compressed INT,uncompressed INT,method INT,crc INT,flags INT,collection TEXT,group_id TEXT,fold TEXT,rank TEXT,PRIMARY KEY(role,key));CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);')
 cached=db.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone();finger=json.dumps(fingerprint,sort_keys=True)
 if not cached or cached[0]!=finger:
  db.execute('DELETE FROM members');db.execute('DELETE FROM settings');db.commit()
  for role,reader in readers.items():
   batch=[];count=0
   for e in reader.entries():
    suffix=PurePosixPath(e.name).suffix.lower()
    if suffix not in (['.jpg','.jpeg','.png'] if role in ['TS','VS'] else ['.json']):continue
    name=e.name.replace('\\','/').lstrip('/')
    if '..' in PurePosixPath(name).parts:raise ValueError('Unsafe archive name')
    key=str(PurePosixPath(name).with_suffix(''));group=camera_group(name)
    batch.append((role,key,e.name,e.disk,e.offset,e.compressed,e.uncompressed,e.method,e.crc,e.flags,name.split('/')[0],group,fold(group),hashlib.sha256(key.encode()).hexdigest()))
    count+=1
    if len(batch)>=5000:db.executemany('INSERT INTO members VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',batch);db.commit();batch=[]
   if batch:db.executemany('INSERT INTO members VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',batch);db.commit()
   print('INDEXED',role,count,flush=True)
  db.execute('CREATE INDEX IF NOT EXISTS sample_bucket ON members(role,fold,collection,rank)');db.execute("INSERT INTO settings VALUES('fingerprint',?)",(finger,));db.commit()
 else:print('Using unchanged archive index',flush=True)
 summary={'original_archives':fingerprint,'stage':'central_directory_inventory_and_pilot','scope':'all central directory entries; full source CRC and every JSON body not scanned','pairs':{},'split_policy':'SHA256 of camera/background identifier with seed edgefire42, 80/10/10; re-split across supplied Training and Validation; not official holdout metrics','pilot_requested':args.pilot_count,'max_side':args.max_side,'class_map':{str(k-1):v for k,v in EXPECTED_NAMES.items()},'polygon_policy':'single polygons only; multipart, RLE, crowd and invalid masks quarantine entire image; no invented masks','polygon_self_intersections_checked':False}
 for image,label in [('TS','TL'),('VS','VL')]:
  counts={r:db.execute('SELECT count(*) FROM members WHERE role=?',(r,)).fetchone()[0] for r in [image,label]}
  missing=db.execute('SELECT count(*) FROM members i LEFT JOIN members l ON l.role=? AND i.key=l.key WHERE i.role=? AND l.key IS NULL',(label,image)).fetchone()[0]
  orphan=db.execute('SELECT count(*) FROM members l LEFT JOIN members i ON i.role=? AND i.key=l.key WHERE l.role=? AND i.key IS NULL',(image,label)).fetchone()[0]
  summary['pairs'][image]={'image_files':counts[image],'label_files':counts[label],'images_without_label':missing,'labels_without_image':orphan}
  if missing or orphan:raise ValueError('Image-label filename pairing mismatch; see index')
 summary['collection_counts']=[dict(r) for r in db.execute("SELECT role,collection,count(*) AS count FROM members WHERE role IN ('TS','VS') GROUP BY role,collection")]
 groups_by_fold={s:{r[0] for r in db.execute("SELECT DISTINCT group_id FROM members WHERE role IN ('TS','VS') AND fold=?",(s,))} for s in ['train','val','test']}
 assert not groups_by_fold['train']&groups_by_fold['val'] and not groups_by_fold['train']&groups_by_fold['test'] and not groups_by_fold['val']&groups_by_fold['test']
 summary['inventory_groups']={k:len(v) for k,v in groups_by_fold.items()};summary['group_overlap']=0
 pilot=out/'pilot_yolo_seg';pilot.mkdir(exist_ok=True)
 for sub in ['images','labels','annotations_original']:
  for split in ['train','val','test']:(pilot/sub/split).mkdir(parents=True,exist_ok=True)
 (out/'qa').mkdir(exist_ok=True);(out/'quarantine').mkdir(exist_ok=True)
 # 각 분할에서 원본 컬렉션별 표본 수를 균등하게 배정합니다.
 accepted=Counter();objects=Counter();errors=Counter();seen_hashes=set();seen_groups=defaultdict(set);qa_count=Counter();written=0;clipped_points=0
 collections=[r[0] for r in db.execute("SELECT DISTINCT collection FROM members WHERE role IN ('TS','VS') ORDER BY collection")]
 with (out/'pilot_manifest.jsonl').open('w',encoding='utf8') as manifest,(out/'quarantine'/'rejected.jsonl').open('w',encoding='utf8') as rejected:
  for split,ratio in [('train',2/3),('val',1/6),('test',1/6)]:
   quota=max(1,round(args.pilot_count*ratio/len(collections)))
   for collection in collections:
    candidates=db.execute("SELECT * FROM members WHERE role IN ('TS','VS') AND fold=? AND collection=? ORDER BY rank LIMIT ?",(split,collection,quota*4)).fetchall();success=0
    for row in candidates:
     if success>=quota:break
     try:
      label_role='TL' if row['role']=='TS' else 'VL';label=db.execute('SELECT * FROM members WHERE role=? AND key=?',(label_role,row['key'])).fetchone()
      original_label=readers[label_role].read(entry_from_row(label),16*1024*1024);data=json.loads(original_label)
      if data.get('info',{}).get('camera_id') and data['info']['camera_id']!=row['group_id']:raise ValueError('camera_group_mismatch')
      original_image=readers[row['role']].read(entry_from_row(row));digest=hashlib.sha256(original_image).hexdigest()
      if digest in seen_hashes:raise ValueError('duplicate_image_in_pilot')
      with Image.open(io.BytesIO(original_image)) as image:
       image.load()
       if image.getexif().get(274,1)!=1:raise ValueError('exif_rotation_requires_review')
       width,height=image.size;segs,classes,clipped=polygons(data,width,height)
       if Path(data['images'][0]['file_name']).name!=PurePosixPath(row['name']).name:raise ValueError('label_filename_mismatch')
       image=image.convert('RGB');image.thumbnail((args.max_side,args.max_side),Image.Resampling.LANCZOS)
       identifier=hashlib.sha256((row['role']+'/'+row['key']).encode()).hexdigest()[:24]
       target=pilot/'images'/split/(identifier+'.jpg');image.save(target,quality=90,subsampling=0)
       text='\n'.join(str(cid)+' '+' '.join(f'{v:.7f}' for point in points for v in point) for cid,points in segs)
       (pilot/'labels'/split/(identifier+'.txt')).write_text(text+'\n' if text else '',encoding='utf8')
       (pilot/'annotations_original'/split/(identifier+'.json')).write_bytes(original_label)
       if qa_count[collection]<2:
        overlay=image.copy().convert('RGBA');draw=ImageDraw.Draw(overlay,'RGBA');colors=[(230,90,40,55),(250,190,20,55),(220,30,30,55),(50,130,230,55),(160,100,220,55),(60,170,100,55)]
        for cid,points in segs:
         pts=[(x*image.width,y*image.height) for x,y in points];draw.polygon(pts,fill=colors[cid],outline=colors[cid][:3]+(255,),width=2);draw.text(pts[0],CLASS_NAMES[cid],fill=(255,255,255,255),stroke_width=1,stroke_fill=(0,0,0,255))
        overlay.convert('RGB').save(out/'qa'/(identifier+'.jpg'),quality=90);qa_count[collection]+=1
      record={'id':identifier,'source_archive':row['role'],'source_member':row['name'],'source_crc32':row['crc'],'raw_sha256':digest,'group_id':row['group_id'],'split':split,'collection':collection,'original_width':width,'original_height':height,'output_width':image.width,'output_height':image.height,'output_file_bytes':target.stat().st_size,'objects':dict(classes),'clipped_boundary_points':clipped}
      manifest.write(json.dumps(record,ensure_ascii=False)+'\n');seen_hashes.add(digest);seen_groups[split].add(row['group_id']);accepted[split]+=1;objects.update(classes);clipped_points+=clipped;success+=1;written+=1
     except Exception as exc:
      reason=str(exc);errors[reason]+=1;rejected.write(json.dumps({'archive':row['role'],'member':row['name'],'reason':reason},ensure_ascii=False)+'\n')
    print('PILOT',split,collection,success,'/',quota,flush=True)
 assert not seen_groups['train']&seen_groups['val'] and not seen_groups['train']&seen_groups['test'] and not seen_groups['val']&seen_groups['test']
 yaml='path: '+pilot.as_posix()+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {name}\n' for i,name in enumerate(CLASS_NAMES))
 (pilot/'dataset.yaml').write_text(yaml,encoding='utf8')
 summary.update({'pilot_written':written,'pilot_counts':dict(accepted),'pilot_object_counts':dict(objects),'quarantine_reasons':dict(errors),'boundary_points_clipped':clipped_points,'pilot_group_counts':{k:len(v) for k,v in seen_groups.items()},'qa_images':sum(qa_count.values()),'pilot_path':str(pilot),'full_data_extracted':False,'trained_vision_model':False})
 (out/'preprocess_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
 for reader in readers.values():reader.close()
 db.close();print('PREPROCESS_COMPLETE',json.dumps(summary,ensure_ascii=True),flush=True)
if __name__=='__main__':main()
