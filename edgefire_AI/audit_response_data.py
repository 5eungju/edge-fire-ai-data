"""Audit event leakage and contradictory labels before response-risk modeling."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter,defaultdict
from pathlib import Path
import psutil
from status_io import write_status


def incident_split(event):
    value=int(hashlib.sha256(('edgefire-response-v1/'+event).encode()).hexdigest()[:8],16)/2**32
    return 'train' if value<.7 else 'val' if value<.85 else 'test'


def audit(root):
    db=sqlite3.connect((root/'response_samples.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    counts=Counter();events=defaultdict(set);features=Counter();missing=Counter();split_labels=defaultdict(Counter)
    rows=db.execute('SELECT event_id,official_split,target,record FROM samples')
    for event,official,target,text in rows:
        record=json.loads(text);counts[target]+=1;events[event].add(official)
        split_labels[incident_split(event)][target]+=1
        for name,value in record['features'].items():
            features[name]+=1
            if value is None:missing[name]+=1
    duplicate_groups=db.execute('SELECT COUNT(*) FROM (SELECT feature_hash FROM samples GROUP BY feature_hash HAVING COUNT(*)>1)').fetchone()[0]
    conflicts=db.execute('SELECT COUNT(*),COALESCE(SUM(n),0) FROM (SELECT COUNT(*) n FROM samples GROUP BY feature_hash HAVING COUNT(DISTINCT target)>1)').fetchone()
    overlap=[event for event,folds in events.items() if len(folds)>1]
    event_groups={s:sorted(event for event in events if incident_split(event)==s) for s in ['train','val','test']}
    blockers=[]
    if conflicts[0]:blockers.append('Identical numeric inputs have contradictory annotation targets; resolve before training')
    if len(counts)<2:blockers.append('Only one target class; a classifier cannot be meaningfully evaluated')
    for split in ['train','val','test']:
        if not event_groups[split]:blockers.append('Empty incident-disjoint '+split+' split')
        if set(split_labels[split])!=set(counts):blockers.append('Missing target classes in '+split+' split')
    report={'phase':'quality_audit_completed','sample_count':sum(counts.values()),'event_count':len(events),
        'target_counts':dict(counts),'official_split_overlapping_event_count':len(overlap),
        'official_split_overlapping_events':overlap,'duplicate_input_group_count':duplicate_groups,
        'contradictory_input_group_count':conflicts[0],'samples_in_contradictory_groups':conflicts[1],
        'missing_feature_counts':dict(missing),'incident_split_groups':event_groups,
        'incident_split_target_counts':{k:dict(v) for k,v in split_labels.items()},
        'numeric_preflight_passed':not blockers,'training_ready':False,'blockers':blockers,
        'operationally_validated':False,
        'target_scope':'Dataset-annotated response risk during wildfire scenarios, not measured pre-ignition probability',
        'remaining_review':['Remove exact duplicates without crossing incident splits',
                            'Review target semantics, units and zero-coded missing fuel values',
                            'Do not treat annotation confidence as calibrated model confidence']}
    (root/'quality_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    db.close()
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--wait-pid',type=int)
    args=p.parse_args();status=args.root/'quality_status.json'
    state={'pid':os.getpid(),'phase':'waiting_for_extraction','training_ready':False}
    write_status(status,state)
    try:
        while True:
            source=args.root/'status.json'
            saved=json.loads(source.read_text(encoding='utf8')) if source.exists() else {}
            if saved.get('phase')=='extracted_quality_review_required':break
            if not args.wait_pid or not psutil.pid_exists(args.wait_pid):
                raise RuntimeError('Extraction has not completed; no live extraction process')
            time.sleep(10)
        report=audit(args.root)
        write_status(status,state|{k:report[k] for k in ['phase','sample_count','training_ready','blockers']})
        print(json.dumps({k:report[k] for k in ['sample_count','event_count','target_counts','training_ready','blockers']},ensure_ascii=False),flush=True)
    except BaseException as exc:
        write_status(status,state|{'phase':'failed','error':str(exc)})
        raise


if __name__=='__main__':main()
