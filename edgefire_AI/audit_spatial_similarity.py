"""카메라 ID 분리 이후에도 장소명/시각 유사성이 겹치는지 조사합니다."""
import argparse,json,sqlite3,re,unicodedata,time,hashlib
from collections import defaultdict,Counter
from pathlib import Path,PurePosixPath
from PIL import Image
import numpy as np

def place(name):
 parts=PurePosixPath(name).parts
 value=parts[1] if len(parts)>1 else name
 value=re.sub(r'_[A-Z]{2}\d{6}$','',value)
 return re.sub(r'[\s\W_]+','',unicodedata.normalize('NFKC',value))

def main():
 p=argparse.ArgumentParser();p.add_argument('--split-plan');p.add_argument('--index',default='E:/AI_Work/edgefire_vision/vision_index.sqlite');p.add_argument('--dataset',default='E:/AI_Work/edgefire_vision_v2');p.add_argument('--output',default='E:/AI_Work/edgefire_vision_v2/quality_audit');a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
 mapping=json.loads(Path(a.split_plan).read_text(encoding='utf8'))['camera_mapping'] if a.split_plan else None
 db=sqlite3.connect('file:'+a.index+'?mode=ro',uri=True);locations=defaultdict(lambda:defaultdict(Counter))
 for name,group,split in db.execute("SELECT name,group_id,fold FROM members WHERE role IN ('TS','VS')"):
  if mapping:split=mapping[group]['split']
  locations[place(name)][split][group]+=1
 overlaps={key:{split:dict(groups) for split,groups in value.items()} for key,value in locations.items() if len(value)>1}
 root=Path(a.dataset);records=[json.loads(line) for line in (root/'pilot_manifest.jsonl').read_text(encoding='utf8').splitlines()];selected=defaultdict(lambda:defaultdict(Counter))
 for row in records:selected[place(row['source_member'])][row['split']][row['group_id']]+=1
 selected_overlap={key:{s:dict(v) for s,v in values.items()} for key,values in selected.items() if len(values)>1}
 (out/'location_name_overlap.json').write_text(json.dumps({'inventory':overlaps,'selected_dataset':selected_overlap},ensure_ascii=False,indent=2),encoding='utf8')
 images=[]
 for i,row in enumerate(records):
  with Image.open(root/'pilot_yolo_seg/images'/row['split']/(row['id']+'.jpg')) as im:
   gray=np.asarray(im.convert('L').resize((9,8)),dtype=np.int16);bits=(gray[:,1:]>gray[:,:-1]).ravel();value=sum(int(bit)<<n for n,bit in enumerate(bits));tiny=np.asarray(im.convert('RGB').resize((16,16)),dtype=np.float32)/255
  images.append((row,value,tiny,tiny.mean(axis=(0,1))))
  if (i+1)%500==0:print('HASHED',i+1,flush=True)
 pairs=[];train=[x for x in images if x[0]['split']=='train'];evaluation=[x for x in images if x[0]['split']!='train']
 for row_a,hash_a,pixels_a,color_a in train:
  for row_b,hash_b,pixels_b,color_b in evaluation:
   distance=(hash_a^hash_b).bit_count()
   if distance<=4 and float(np.max(np.abs(color_a-color_b)))<.05:
    mse=float(np.mean((pixels_a-pixels_b)**2))
    if mse<.006:pairs.append({'train_id':row_a['id'],'evaluation_id':row_b['id'],'evaluation_split':row_b['split'],'dhash_distance':distance,'tiny_rgb_mse':mse,'same_location_name':place(row_a['source_member'])==place(row_b['source_member'])})
 pairs.sort(key=lambda x:(x['tiny_rgb_mse'],x['dhash_distance']));(out/'visual_similarity_candidates.json').write_text(json.dumps(pairs,indent=2),encoding='utf8')
 summary={'manifest_sha256':hashlib.sha256((root/'pilot_manifest.jsonl').read_bytes()).hexdigest(),'inventory_location_name_count':len(locations),'inventory_location_name_overlap_count':len(overlaps),'selected_location_name_overlap_count':len(selected_overlap),'selected_overlap_location_names':sorted(selected_overlap),'selected_images_with_overlapping_location_name':sum(1 for r in records if place(r['source_member']) in selected_overlap),'cross_split_visual_similarity_candidates':len(pairs),'images_hashed':len(images),'elapsed_seconds':round(time.monotonic()-started,1),'interpretation':'Location-name matches and dHash+tiny RGB similarity are review flags, not proof of identical physical locations or duplicate images. No files removed. Camera-ID split is not a verified spatial holdout.'}
 (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8');print('QUALITY_AUDIT_COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True);db.close()
if __name__=='__main__':main()
