"""장소명·카메라 연결 성분을 보존하는 컬렉션 균형 분할 계획."""
import os
os.environ['OMP_NUM_THREADS']='1'
import argparse,json,sqlite3,time,hashlib
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from audit_spatial_similarity import place

def conservative_place(name):
 value=place(name)
 for mountain in ['시루봉','춘갑봉']:
  if mountain in value:return '보수적산악권역:'+mountain
 return value

class Components:
 def __init__(self):self.parent={}
 def find(self,x):
  self.parent.setdefault(x,x)
  if self.parent[x]!=x:self.parent[x]=self.find(self.parent[x])
  return self.parent[x]
 def union(self,a,b):
  a,b=self.find(a),self.find(b)
  if a!=b:self.parent[max(a,b)]=min(a,b)

def main():
 p=argparse.ArgumentParser();p.add_argument('--reviewed-visual-links');p.add_argument('--index',default='E:/AI_Work/edgefire_vision/vision_index.sqlite');p.add_argument('--output',default='E:/AI_Work/edgefire_spatial_plan');a=p.parse_args();out=Path(a.output);out.mkdir(exist_ok=True);started=time.monotonic();db=sqlite3.connect('file:'+a.index+'?mode=ro',uri=True);components=Components();aggregate=Counter();original_names=defaultdict(set)
 for name,camera,collection in db.execute("SELECT name,group_id,collection FROM members WHERE role IN ('TS','VS')"):
  loc=conservative_place(name);components.union('camera:'+camera,'place:'+loc);aggregate[(camera,loc,collection)]+=1;original_names[loc].add(place(name))
 reviewed_links=[]
 if a.reviewed_visual_links:
  reviewed_links=json.loads(Path(a.reviewed_visual_links).read_text(encoding='utf8'))['approved_links']
  available={camera for camera,_,_ in aggregate}
  for link in reviewed_links:
   assert link['reviewed_by']=='visual_review' and link['camera_a'] in available and link['camera_b'] in available
   components.union('camera:'+link['camera_a'],'camera:'+link['camera_b'])
 group_places=defaultdict(set);group_cameras=defaultdict(set);group_counts=defaultdict(Counter)
 for (camera,loc,collection),count in aggregate.items():
  group=components.find('camera:'+camera);group_places[group].add(loc);group_cameras[group].add(camera);group_counts[group][collection]+=count
 groups=sorted(group_counts);collections=sorted({c for counter in group_counts.values() for c in counter});matrix=np.array([[group_counts[g][c] for c in collections] for g in groups],dtype=float);n,m=matrix.shape;ratios=np.array([.7,.15,.15]);totals=matrix.sum(axis=0);variables=n*3+3*m;objective=np.zeros(variables);lower=np.zeros(variables);upper=np.full(variables,np.inf);upper[:n*3]=1;integrality=np.zeros(variables);integrality[:n*3]=1;rows=[];lo=[];hi=[]
 def constraint(items,l,u):
  row=np.zeros(variables)
  for index,value in items:row[index]=value
  rows.append(row);lo.append(l);hi.append(u)
 for g in range(n):constraint([(g*3+s,1) for s in range(3)],1,1)
 for s in range(3):
  for c in range(m):
   d=n*3+s*m+c;objective[d]=1/(max(1,totals[c])*ratios[s]);target=totals[c]*ratios[s]
   constraint([(g*3+s,matrix[g,c]) for g in range(n)]+[(d,-1)],-np.inf,target)
   constraint([(g*3+s,-matrix[g,c]) for g in range(n)]+[(d,-1)],-np.inf,-target)
   present=[g for g in range(n) if matrix[g,c]>0]
   if len(present)>=3 or s==0:constraint([(g*3+s,1) for g in present],1,np.inf)
 print('SPATIAL_GROUPS',n,'COLLECTIONS',m,flush=True)
 result=milp(objective,integrality=integrality,bounds=Bounds(lower,upper),constraints=LinearConstraint(np.array(rows),np.array(lo),np.array(hi)),options={'time_limit':20.0,'mip_rel_gap':.02})
 if result.x is None:raise RuntimeError('No feasible spatial split: '+result.message)
 assignment=result.x[:n*3].reshape(n,3);assert np.max(np.abs(assignment-np.round(assignment)))<1e-5;folds=['train','val','test'];mapping={};split_counts={s:Counter() for s in folds};details=[]
 for i,g in enumerate(groups):
  split=folds[int(np.argmax(assignment[i]))];split_counts[split].update(group_counts[g]);key=hashlib.sha256('|'.join(sorted(group_places[g])).encode()).hexdigest()[:20]
  details.append({'group_key':key,'split':split,'places':sorted(group_places[g]),'camera_ids':sorted(group_cameras[g]),'collection_counts':dict(group_counts[g])})
  for camera in group_cameras[g]:mapping[camera]={'split':split,'group_key':key}
 assert len(mapping)==len({k[0] for k in aggregate})
 report={'reviewed_background_links':reviewed_links,'solver_status':int(result.status),'solver_message':result.message,'solver_satisfied_requested_gap':bool(result.success),'exact_optimum_proven':bool(result.success and (result.mip_gap or 0)<1e-10),'objective':float(result.fun),'relative_gap':float(result.mip_gap) if result.mip_gap is not None else None,'target_ratios':dict(zip(folds,ratios.tolist())),'spatial_components':n,'camera_count':len(mapping),'collection_counts_by_split':{s:dict(v) for s,v in split_counts.items()},'coverage_group_counts':{c:int(np.sum(matrix[:,j]>0)) for j,c in enumerate(collections)},'component_assignments':details,'place_name_aliases':{loc:sorted(values) for loc,values in original_names.items() if len(values)>1},'camera_mapping':mapping,'elapsed_seconds':round(time.monotonic()-started,1),'policy':'All matching normalized location names and shared camera IDs stay together. Names containing 시루봉 or 춘갑봉 conservatively merge to mountain-name regions even without verified coordinates. This is name-based conservative grouping, not certified geographic separation. New evaluation split; not comparable directly to old test. No model scores used in split optimization.'}
 (out/'spatial_split_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('SPATIAL_PLAN_COMPLETE',n,len(mapping),report['solver_message'],flush=True);db.close()
if __name__=='__main__':main()
