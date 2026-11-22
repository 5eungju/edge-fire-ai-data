"""Validation-only comparison of class weighting; preserve earlier research run."""
import argparse
import csv
import json
import os
import shutil
from pathlib import Path

os.environ['OMP_NUM_THREADS']='2'
os.environ['MKL_NUM_THREADS']='2'


def main():
    import numpy as np
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import f1_score,accuracy_score,classification_report,confusion_matrix
    from threadpoolctl import threadpool_limits
    from status_io import write_status
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();root=args.root.resolve()
    out=root/'response_models';old=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
    backup=out/'initial_expanded_comparison.json'
    if backup.exists():raise FileExistsError('Preserve previous weighting experiment')
    shutil.copy2(out/'comparison.json',backup);shutil.copy2(out/'response_hgb.joblib',out/'initial_response_hgb.joblib')
    names=old['feature_names'];classes=old['classes'];rows={s:[] for s in ['train','val','test']};targets={s:[] for s in rows}
    with (root/'response_data/samples.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            rows[row['split']].append([float(row[n]) for n in names]);targets[row['split']].append(classes.index(row['target']))
    x={s:np.array(v,dtype=np.float32) for s,v in rows.items()};y={s:np.array(v) for s,v in targets.items()}
    del rows,targets
    counts=np.bincount(y['train'],minlength=len(classes));weights=len(y['train'])/(len(classes)*counts)
    best_score=old['validation'][old['selected_model']]['macro_f1'];best=None;best_mode=None;history={}
    def evaluate(truth,pred):
        return dict(macro_f1=float(f1_score(truth,pred,average='macro',labels=list(range(len(classes))),zero_division=0)),
            accuracy=float(accuracy_score(truth,pred)),per_class=classification_report(truth,pred,labels=list(range(len(classes))),
            target_names=classes,output_dict=True,zero_division=0),confusion_matrix=confusion_matrix(truth,pred,labels=list(range(len(classes)))).tolist())
    with threadpool_limits(limits=2):
      for mode,power in [('unweighted',0),('sqrt_weighted',.5)]:
        write_status(root/'weighting_status.json',dict(phase='training',mode=mode,pid=os.getpid()))
        model=HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=15,learning_rate=.08,
            l2_regularization=1,early_stopping=False,random_state=42)
        model.fit(x['train'],y['train'],sample_weight=(weights**power)[y['train']])
        score=evaluate(y['val'],model.predict(x['val']));history[mode]=score
        if score['macro_f1']>best_score:best_score=score['macro_f1'];best=model;best_mode=mode
      if best is not None:
        joblib.dump(best,out/'response_hgb.joblib');old['selected_model']='histogram_boosting'
        old['validation']['histogram_boosting']=history[best_mode]
        old['selected_test']=evaluate(y['test'],best.predict(x['test']))
        old['configuration']['selected_class_weighting']=best_mode
    old['weighting_validation_comparison']=history
    old['validation_baseline_exceeded']=best_score>old['validation']['majority_baseline']['macro_f1']
    old['deployment_decision']='review_required' if old['validation_baseline_exceeded'] else 'rejected_failed_validation_baseline'
    old['limitations']+=['Validation reused for weighting choice; test previously evaluated. Independent external evaluation still required.']
    write_status(out/'comparison.json',old)
    write_status(root/'weighting_status.json',dict(phase='completed',best_validation_macro_f1=best_score,
        selected_weighting=best_mode,baseline_exceeded=old['validation_baseline_exceeded']))
    print(json.dumps(dict(validation_macro_f1=best_score,selected_weighting=best_mode,baseline_exceeded=old['validation_baseline_exceeded'])))


if __name__=='__main__':main()
