"""Create an auditable four-class research dataset; preserve all original labels."""
import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter,defaultdict
from pathlib import Path
from audit_response_data import incident_split

CLASSES = ['낮음','보통','높음','매우 높음']
ALIASES = {'낮음':'낮음','보통':'보통','중간':'보통','높음':'높음','매우높음':'매우 높음'}


def normalize_target(value):
    return ALIASES.get(''.join(value.split()))


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'samples.csv').exists():raise FileExistsError('Preserve completed export; choose a new directory')
    db=sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro',uri=True)
    db.execute('CREATE TEMP TABLE normalized(id TEXT PRIMARY KEY,event TEXT,split TEXT,hash TEXT,target TEXT)')
    reasons=Counter();normalizations=Counter();groups=defaultdict(lambda:{'targets':set(),'splits':set()})
    with (args.output/'excluded.csv').open('w',encoding='utf8',newline='') as rejected:
        exclusion=csv.writer(rejected);exclusion.writerow(['id','raw_target','reason'])
        for identifier,event,raw,digest in db.execute('SELECT id,event_id,target,feature_hash FROM samples ORDER BY id'):
            target=normalize_target(raw)
            if target is None:
                reasons['outside_reviewed_four_class_scope']+=1
                exclusion.writerow([identifier,raw,'outside_reviewed_four_class_scope'])
                continue
            split=incident_split(event);groups[digest]['targets'].add(target);groups[digest]['splits'].add(split)
            normalizations[raw+' -> '+target]+=1
            db.execute('INSERT INTO normalized VALUES(?,?,?,?,?)',(identifier,event,split,digest,target))
        columns=None;writer=None;seen=set();counts=defaultdict(Counter);events=defaultdict(set);zero=Counter();total=0
        with (args.output/'samples.csv.partial').open('w',encoding='utf8',newline='') as stream:
            for identifier,event,split,digest,target,text in db.execute('SELECT n.id,n.event,n.split,n.hash,n.target,s.record FROM normalized n JOIN samples s ON s.id=n.id ORDER BY n.id'):
                group=groups[digest];reason=None
                if len(group['targets'])>1:reason='contradictory_targets_for_identical_inputs'
                elif len(group['splits'])>1:reason='identical_inputs_cross_incident_splits'
                elif digest in seen:reason='duplicate_identical_input_within_split'
                if reason:
                    reasons[reason]+=1;exclusion.writerow([identifier,target,reason]);continue
                record=json.loads(text);inputs=record['features']
                if columns is None:
                    columns=sorted(inputs);writer=csv.writer(stream)
                    writer.writerow(['id','event_id','split','target','feature_sha256']+columns)
                if sorted(inputs)!=columns:raise ValueError('Inconsistent numeric feature schema')
                writer.writerow([identifier,event,split,target,digest]+[inputs[k] for k in columns])
                for k in columns:
                    if inputs[k]==0:zero[k]+=1
                seen.add(digest);counts[split][target]+=1;events[split].add(event);total+=1
    blockers=[]
    for split in ['train','val','test']:
        if set(counts[split])!=set(CLASSES):blockers.append('Missing class in '+split)
    for a,b in [('train','val'),('train','test'),('val','test')]:
        if events[a]&events[b]:raise ValueError('Incident leakage after cleaning')
    partial=args.output/'samples.csv.partial';partial.replace(args.output/'samples.csv')
    with (args.output/'samples.csv').open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'phase':'cleaning_completed','scope':'Four-class annotated response-risk research only',
        'classes':CLASSES,'accepted':total,'excluded':dict(reasons),'normalizations':dict(normalizations),
        'split_target_counts':{s:dict(v) for s,v in counts.items()},'split_event_counts':{s:len(v) for s,v in events.items()},
        'feature_names':columns,'zero_value_counts':dict(zero),'samples_csv_sha256':digest,
        'research_experiment_eligible':not blockers,'operationally_validated':False,'blockers':blockers,
        'limitations':['Very-low and ambiguous labels are preserved in exclusions, not re-labeled.',
            'Middle and normal are explicitly merged as the reviewed medium category.',
            'Zero-coded fuel values and physical units remain unverified; no sensor deployment.',
            'The target is an annotation during a fire scenario, not a pre-ignition probability.',
            'Strong class imbalance requires class-specific recall and majority baseline comparison.']}
    (args.output/'cleaning_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    db.close();print(json.dumps({k:report[k] for k in ['accepted','excluded','split_target_counts','research_experiment_eligible','blockers']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
