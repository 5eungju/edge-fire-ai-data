"""Incident-disjoint research comparison: histogram boosting vs a weighted neural MLP."""
import argparse
import copy
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from status_io import write_status


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=20)
    args=parser.parse_args()
    os.environ['OMP_NUM_THREADS']='2';os.environ['MKL_NUM_THREADS']='2'
    import numpy as np
    import torch
    import sklearn
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score,f1_score,classification_report,confusion_matrix
    from threadpoolctl import threadpool_limits
    if args.output.exists():raise FileExistsError('Preserve experiment outputs; choose a new directory')
    args.output.mkdir(parents=True)
    state={'pid':os.getpid(),'phase':'loading_cleaned_data','operationally_validated':False}
    started=time.monotonic()
    def update(**values):
        state.update(values,elapsed_seconds=round(time.monotonic()-started,1))
        write_status(args.output/'status.json',state)
    update()
    try:
        report=json.loads((args.data/'cleaning_report.json').read_text(encoding='utf8'))
        if not report['research_experiment_eligible']:raise ValueError('Research dataset failed cleaning checks')
        data=args.data/'samples.csv'
        with data.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=report['samples_csv_sha256']:raise ValueError('Cleaned CSV changed')
        names=report['feature_names'];classes=report['classes'];k=len(classes)
        rows={s:[] for s in ['train','val','test']};targets={s:[] for s in rows};events={s:set() for s in rows};seen=set()
        with data.open(encoding='utf8',newline='') as stream:
            for row in csv.DictReader(stream):
                split=row['split'];values=[float(row[name]) for name in names]
                if not all(np.isfinite(values)):raise ValueError('Nonfinite numeric input')
                if row['feature_sha256'] in seen:raise ValueError('Duplicate input leaked into cleaned CSV')
                seen.add(row['feature_sha256']);events[split].add(row['event_id'])
                rows[split].append(values);targets[split].append(classes.index(row['target']))
        for a,b in [('train','val'),('train','test'),('val','test')]:
            if events[a]&events[b]:raise ValueError('Incident leakage')
        x={s:np.asarray(v,dtype=np.float32) for s,v in rows.items()}
        y={s:np.asarray(v,dtype=np.int64) for s,v in targets.items()}
        del rows,targets,seen
        if any(set(y[s])!=set(range(k)) for s in y):raise ValueError('Missing class in a split')
        def evaluate(truth,predicted):
            return {'accuracy':float(accuracy_score(truth,predicted)),
                'macro_f1':float(f1_score(truth,predicted,labels=list(range(k)),average='macro',zero_division=0)),
                'per_class':classification_report(truth,predicted,labels=list(range(k)),target_names=classes,output_dict=True,zero_division=0),
                'confusion_matrix':confusion_matrix(truth,predicted,labels=list(range(k))).tolist()}
        histogram=np.bincount(y['train'],minlength=k)
        majority=int(histogram.argmax())
        baseline=evaluate(y['val'],np.full_like(y['val'],majority))
        balanced=len(y['train'])/(k*histogram)
        with threadpool_limits(limits=2):
            update(phase='training_histogram_boosting',split_counts={s:len(v) for s,v in y.items()})
            boosting=HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=15,learning_rate=.08,
                l2_regularization=1.,early_stopping=False,random_state=42)
            boosting.fit(x['train'],y['train'],sample_weight=balanced[y['train']])
            boosting_val=evaluate(y['val'],boosting.predict(x['val']))
            joblib.dump(boosting,args.output/'response_hgb.joblib')
        torch.set_num_threads(2);torch.manual_seed(42);np.random.seed(42)
        mean=x['train'].mean(axis=0);scale=x['train'].std(axis=0);scale[scale<1e-6]=1.
        network=torch.nn.Sequential(torch.nn.Linear(len(names),96),torch.nn.SiLU(),torch.nn.Dropout(.15),
            torch.nn.Linear(96,48),torch.nn.SiLU(),torch.nn.Dropout(.15),torch.nn.Linear(48,k))
        optimizer=torch.optim.AdamW(network.parameters(),lr=.001,weight_decay=.0001)
        criterion=torch.nn.CrossEntropyLoss(weight=torch.tensor(balanced,dtype=torch.float32))
        inputs={s:torch.from_numpy((values-mean)/scale) for s,values in x.items()}
        labels=torch.from_numpy(y['train'])
        loader=torch.utils.data.DataLoader(torch.utils.data.TensorDataset(inputs['train'],labels),batch_size=1024,shuffle=True,num_workers=0)
        def neural_predict(split):
            network.eval()
            with torch.inference_mode():
                return torch.cat([network(batch).argmax(1) for batch in inputs[split].split(4096)]).numpy()
        best_score=-1.;best_weights=None;best_epoch=0;history=[]
        for epoch in range(1,args.epochs+1):
            network.train();loss_sum=0.
            for batch,target in loader:
                optimizer.zero_grad();loss=criterion(network(batch),target);loss.backward();optimizer.step()
                loss_sum+=float(loss.detach())*len(target)
            score=evaluate(y['val'],neural_predict('val'))['macro_f1']
            history.append({'epoch':epoch,'loss':loss_sum/len(labels),'validation_macro_f1':score})
            if score>best_score:
                best_score=score;best_weights=copy.deepcopy(network.state_dict());best_epoch=epoch
                torch.save({'state_dict':best_weights,'feature_names':names,'classes':classes,'mean':mean.tolist(),
                    'scale':scale.tolist(),'architecture':[len(names),96,48,k],'epoch':epoch,
                    'dataset_sha256':digest,'operationally_validated':False},args.output/'response_mlp.pt')
            update(phase='training_neural_mlp',epoch=epoch,epochs=args.epochs,best_epoch=best_epoch,
                   validation_macro_f1=score,best_validation_macro_f1=best_score)
            if epoch-best_epoch>=4:break
        network.load_state_dict(best_weights)
        neural_val=evaluate(y['val'],neural_predict('val'))
        selected='neural_mlp' if neural_val['macro_f1']>boosting_val['macro_f1'] else 'histogram_boosting'
        beats_baseline=max(neural_val['macro_f1'],boosting_val['macro_f1'])>baseline['macro_f1']
        update(phase='evaluating_selected_test',selected_model=selected)
        with threadpool_limits(limits=2):
            prediction=neural_predict('test') if selected=='neural_mlp' else boosting.predict(x['test'])
        result={'scope':'Four-class dataset-annotated response risk; not an ignition probability',
            'selected_model':selected,'selection_rule':'Highest incident-disjoint validation macro F1',
            'test_used_for_selection':False,'operationally_validated':False,
            'validation_baseline_exceeded':beats_baseline,
            'deployment_decision':'review_required' if beats_baseline else 'rejected_failed_validation_baseline',
            'dataset_sha256':digest,'feature_names':names,'classes':classes,
            'split_counts':{s:len(v) for s,v in y.items()},'event_counts':{s:len(v) for s,v in events.items()},
            'validation':{'majority_baseline':baseline,'histogram_boosting':boosting_val,'neural_mlp':neural_val},
            'selected_test':evaluate(y['test'],prediction),'neural_history':history,
            'configuration':{'seed':42,'class_weights':balanced.tolist(),'mlp_layers':[len(names),96,48,k],
                'mlp_dropout':.15,'optimizer':'AdamW','scaling_fit':'training split only'},
            'versions':{'python':sys.version,'torch':torch.__version__,'sklearn':sklearn.__version__},
            'limitations':report['limitations']}
        (args.output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
        update(phase='completed',selected_model=selected,comparison_report=str(args.output/'comparison.json'))
        print(json.dumps({'selected_model':selected,'validation_macro_f1':{n:v['macro_f1'] for n,v in result['validation'].items()},'selected_test_macro_f1':result['selected_test']['macro_f1']}),flush=True)
    except BaseException as exc:
        update(phase='failed',error=str(exc));raise


if __name__=='__main__':main()
