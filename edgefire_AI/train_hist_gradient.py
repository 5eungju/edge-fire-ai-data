"""로컬 AI 허브 ZIP에서 사건별 표본을 추출해 기준 모델을 학습합니다."""
from pathlib import Path
import json,zipfile,collections,random,sys,joblib
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier
from sklearn.metrics import classification_report,confusion_matrix,balanced_accuracy_score,f1_score
from features import FEATURES,LABELS,normalize_label,vector
BASE=Path(__file__).resolve().parent
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'Downloads'
folder=next(root.glob('38.*'));rng=random.Random(42);records=[];unknown=collections.Counter()
for z in sorted(folder.rglob('TL_*.zip')):
 rawpath=next(folder.rglob(z.name.replace('TL_','TS_')))
 with zipfile.ZipFile(z) as labels,zipfile.ZipFile(rawpath) as raw:
  byevent=collections.defaultdict(list)
  for name in labels.namelist():
   if name.endswith('.json'):byevent[Path(name).stem.split('_')[0]].append(name)
  source={Path(n).stem:n for n in raw.namelist() if n.endswith('.json')}
  for event,names in sorted(byevent.items()):
   for name in rng.sample(sorted(names),min(250,len(names))):
    lab=json.loads(labels.read(name))['labelling_data_info'];verdict=lab.get('decision_answer',{}).get('safety_verdict',{});label=normalize_label(verdict.get('safety_level',''))
    if label is None:unknown[verdict.get('safety_level','')]+=1;continue
    sid=Path(name).stem.replace('_T_P','_S_P');source_name=source.get(sid)
    if source_name is None:continue
    d=json.loads(raw.read(source_name));src=d['source_data_info'];obs={**src.get('weather_conditions',{}),**src.get('terrain_conditions',{})}
    records.append({'id':Path(name).stem,'event':event,'x':vector(obs),'y':label})
 print(z.name,'sampled',len(records),flush=True)
X=np.array([r['x'] for r in records]);y=np.array([r['y'] for r in records]);groups=np.array([r['event'] for r in records])
train,test=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(X,y,groups))
assert not set(groups[train]) & set(groups[test])

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score
from threadpoolctl import threadpool_limits
baseline=json.loads((BASE/'metrics.json').read_text(encoding='utf8'))
assert baseline['sample_rows']==len(records)
assert baseline['test_incidents']==sorted(set(groups[test]))
results={'random_forest':{'macro_f1':baseline['model_macro_f1'],'accuracy':baseline['classification_report']['accuracy'],'balanced_accuracy':baseline['model_balanced_accuracy']},'majority_baseline':{'macro_f1':baseline['dummy_macro_f1'],'accuracy':float(np.mean(y[test]==3))}}
models={
'hist_gradient_boosting':make_pipeline(SimpleImputer(strategy='median',add_indicator=True),HistGradientBoostingClassifier(max_iter=180,max_leaf_nodes=15,learning_rate=.05,l2_regularization=1.,class_weight='balanced',early_stopping=False,random_state=42)),
'logistic_regression':make_pipeline(SimpleImputer(strategy='median',add_indicator=True),StandardScaler(),LogisticRegression(class_weight='balanced',max_iter=1500,random_state=42))}
for name,model in models.items():
 with threadpool_limits(limits=2):model.fit(X[train],y[train]);pred=model.predict(X[test])
 report=classification_report(y[test],pred,labels=list(range(5)),target_names=LABELS,zero_division=0,output_dict=True)
 result={'macro_f1':float(f1_score(y[test],pred,labels=list(range(5)),average='macro',zero_division=0)),'accuracy':float(accuracy_score(y[test],pred)),'balanced_accuracy':float(balanced_accuracy_score(y[test],pred)),'classification_report':report}
 results[name]=result
 if name=='hist_gradient_boosting':
  metrics={**baseline,'model_version':'prototype-hgb-2026-11-20','model_type':'HistGradientBoostingClassifier','model_macro_f1':result['macro_f1'],'model_balanced_accuracy':result['balanced_accuracy'],'classification_report':report,'confusion_matrix':confusion_matrix(y[test],pred,labels=list(range(5))).tolist(),'hyperparameters':{'max_iter':180,'max_leaf_nodes':15,'learning_rate':.05,'l2_regularization':1.,'class_weight':'balanced','early_stopping':False,'random_state':42}}
  joblib.dump({'model':model,'metrics':metrics},BASE/'wildfire_hgb.joblib')
  (BASE/'hist_gradient_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')
 print(name,json.dumps(result,ensure_ascii=True),flush=True)
comparison={'task':'existing wildfire annotation classification','same_sample_and_incident_split':True,'sample_rows':len(records),'train_rows':len(train),'test_rows':len(test),'train_incidents':len(set(groups[train])),'test_incidents':len(set(groups[test])),'results':results,'note':'One internal holdout comparison; no external validation or operational approval.'}
(BASE/'model_comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf8')
print('COMPARISON_COMPLETE',flush=True)
