"""전체 라벨 JSON의 구조·좌표·클래스 분포 검사. 원본 이미지 전체 디코딩은 하지 않음."""
import argparse, json, sqlite3, time
from pathlib import Path
from collections import Counter
from split_zip_reader import ZipReader,Entry
from prepare_vision_dataset import polygons

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='E:/AI_Work/edgefire_vision');a=p.parse_args();root=Path(a.root)
 db=sqlite3.connect('file:'+str(root/'vision_index.sqlite').replace('\\','/')+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 output=root/'full_label_audit';output.mkdir(exist_ok=True)
 if (output/'summary.json').exists():raise ValueError('Audit already completed')
 counts=Counter();objects=Counter();dimensions=Counter();errors=Counter();started=time.monotonic();total=0
 def save(phase):
  state={'phase':phase,'labels_checked':total,'counts':dict(counts),'object_counts':dict(objects),'dimension_counts':dict(dimensions),'issues':dict(errors),'elapsed_seconds':round(time.monotonic()-started,1),'scope':'All JSON bodies: CRC, single-polygon conversion validity, filename and camera ID; dimensions checked against JSON only, not every image decode. Self-intersections and near-duplicates not checked.'}
  tmp=output/'status.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(output/'status.json');return state
 with (output/'issues.jsonl').open('w',encoding='utf8') as issues:
  for role in ['TL','VL']:
   archive=Path(db.execute('SELECT name FROM members WHERE role=? LIMIT 1',(role,)).fetchone()[0])
   fingerprints=json.loads(db.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0]);reader=ZipReader(fingerprints[role][-1]['path'])
   for row in db.execute('SELECT * FROM members WHERE role=? ORDER BY disk,offset',(role,)):
    total+=1;counts[role]+=1
    try:
     data=json.loads(reader.read(Entry(row['name'],row['disk'],row['offset'],row['compressed'],row['uncompressed'],row['method'],row['crc'],row['flags']),16*1024*1024));im=data['images'][0]
     if not isinstance(im['width'],int) or not isinstance(im['height'],int) or im['width']<=0 or im['height']<=0:raise ValueError('invalid_dimensions')
     _,classes,clipped=polygons(data,im['width'],im['height']);objects.update(classes);dimensions[str(im['width'])+'x'+str(im['height'])]+=1
     if Path(im['file_name']).stem!=Path(row['name']).stem:raise ValueError('label_filename_mismatch')
     if data.get('info',{}).get('camera_id') and data['info']['camera_id']!=row['group_id']:raise ValueError('camera_group_mismatch')
     if clipped:counts['labels_with_boundary_clipping']+=1
     counts['valid_single_polygon_format']+=1
    except Exception as exc:
     reason=str(exc);errors[reason]+=1;issues.write(json.dumps({'archive':role,'member':row['name'],'reason':reason},ensure_ascii=False)+'\n')
    if total%5000==0:save('running')
   reader.close()
 state=save('completed');(output/'summary.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');db.close();print(json.dumps(state,ensure_ascii=False))
if __name__=='__main__':main()
