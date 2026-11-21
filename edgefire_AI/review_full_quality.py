"""Review full-export findings while preserving folds and excluding conflicts.

No images are moved between folds. Known cross-fold background components keep
their existing train rows (or val before test), excluding evaluation conflicts.
Thus this operation cannot introduce new cross-fold image pairs. It does not
unblock the old V4 plan or train/promote a model.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from status_io import write_status


class Components:
    def __init__(self,names): self.parent={name:name for name in names}
    def find(self,name):
        while self.parent[name]!=name:
            self.parent[name]=self.parent[self.parent[name]];name=self.parent[name]
        return name
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        if a!=b:self.parent[max(a,b)]=min(a,b)


def stable_fold_policy(camera_rows,links):
    camera_site={};site_split={}
    for camera,site,split in camera_rows:
        if split not in ('train','val','test'):raise ValueError('Invalid original fold')
        if camera in camera_site and camera_site[camera]!=site:raise ValueError('Camera maps to multiple frozen sites')
        if site in site_split and site_split[site]!=split:raise ValueError('Frozen site spans folds')
        camera_site[camera]=site;site_split[site]=split
    graph=Components(site_split)
    unused=[]
    for link in links:
        if link.get('reviewed_by')!='visual_review' or not link.get('reason'):
            raise ValueError('Background grouping requires explicit visual review')
        a,b=link['camera_a'],link['camera_b']
        if a not in camera_site or b not in camera_site:unused.append([a,b]);continue
        graph.union(camera_site[a],camera_site[b])
    members=defaultdict(list)
    for site in site_split:members[graph.find(site)].append(site)
    priority={'train':0,'val':1,'test':2}
    policies={}
    for sites in members.values():
        sites=sorted(sites);folds={site_split[s] for s in sites}
        keep=min(folds,key=priority.get)
        canonical=sites[0] if len(sites)==1 else hashlib.sha256('|'.join(sites).encode()).hexdigest()[:20]
        for site in sites:
            policies[site]={'canonical_site':canonical,'keep':site_split[site]==keep,
                            'original_split':site_split[site],'kept_split':keep,
                            'component_sites':sites,'conflicted':len(folds)>1}
    return policies,camera_site,unused


def read_only(path):return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pipeline',type=Path,required=True,help='Root containing active preprocess/quality/uncapped/metadata/integrity folders')
    parser.add_argument('--reviewed-links',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.pipeline
    states={name:json.loads((root/name/'status.json').read_text(encoding='utf-8')) for name in ['preprocess','quality','uncapped','metadata','integrity']}
    count=states['preprocess'].get('accepted')
    if not (states['preprocess']['phase']=='export_completed_quality_review_required'
            and states['quality'].get('full_export_completed')
            and states['uncapped'].get('full_source_audit_completed')
            and states['metadata'].get('full_export_completed')
            and states['integrity'].get('complete') and states['integrity'].get('images_checked')==count):
        raise ValueError('All full-export scans and the final fresh integrity sweep must finish first')
    args.output.mkdir(parents=True,exist_ok=True)
    final=args.output/'admission.sqlite';temporary=args.output/'admission.sqlite.partial'
    if final.exists() or temporary.exists():raise FileExistsError('Preserve prior review; choose a new output directory')
    links_bytes=args.reviewed_links.read_bytes();links=json.loads(links_bytes)['approved_links']
    meta=read_only(root/'metadata/metadata.sqlite')
    meta.execute('ATTACH DATABASE ? AS p',((root/'preprocess/progress.sqlite').resolve().as_uri()+'?mode=ro',))
    meta.execute('ATTACH DATABASE ? AS q',((root/'quality/quality.sqlite').resolve().as_uri()+'?mode=ro',))
    meta.execute('ATTACH DATABASE ? AS u',((root/'uncapped/recheck.sqlite').resolve().as_uri()+'?mode=ro',))
    meta.execute('ATTACH DATABASE ? AS v',((root/'integrity/integrity.sqlite').resolve().as_uri()+'?mode=ro',))
    meta.execute('PRAGMA main.cache_size=-65536')
    meta.execute('PRAGMA p.cache_size=-65536')
    meta.execute('PRAGMA q.cache_size=-131072')
    for query in [
        'SELECT id FROM images EXCEPT SELECT id FROM p.accepted',
        'SELECT id FROM p.accepted EXCEPT SELECT id FROM images',
        'SELECT id FROM images EXCEPT SELECT id FROM q.sketches',
        'SELECT id FROM q.sketches EXCEPT SELECT id FROM images',
        'SELECT DISTINCT shard FROM images EXCEPT SELECT name FROM v.verified']:
        if meta.execute(query+' LIMIT 1').fetchone():raise ValueError('Full-scan ID/shard coverage differs')
    if meta.execute('SELECT 1 FROM images m JOIN p.accepted p ON p.id=m.id WHERE m.raw_sha!=p.raw_sha256 OR m.split!=p.split LIMIT 1').fetchone():
        raise ValueError('Accepted source SHA or original fold differs from metadata')
    if meta.execute('SELECT 1 FROM images m JOIN q.sketches q ON q.id=m.id WHERE m.split!=q.split OR m.site!=q.site LIMIT 1').fetchone():
        raise ValueError('Pixel-audit fold/site differs from metadata')
    rows=meta.execute('SELECT DISTINCT camera,site,split FROM images').fetchall()
    policies,camera_site,unused=stable_fold_policy(rows,links)
    pairs=meta.execute('''WITH pairs AS (SELECT a,b FROM q.candidates UNION SELECT a,b FROM u.candidates)
       SELECT pairs.a,pairs.b,x.site,y.site,x.camera,y.camera FROM pairs
       JOIN images x ON x.id=pairs.a JOIN images y ON y.id=pairs.b''').fetchall()
    unknown=[{'a':a,'b':b,'camera_a':ca,'camera_b':cb} for a,b,sa,sb,ca,cb in pairs
             if policies[sa]['canonical_site']!=policies[sb]['canonical_site']]
    if unknown:
        write_status(args.output/'status.json',{'phase':'additional_visual_review_required','training_ready':False,'unreviewed_candidate_pairs':len(unknown),'examples':unknown[:20]})
        raise ValueError('Candidate camera links still require visual review')
    issues=defaultdict(list)
    for identifier,reason in meta.execute('SELECT id,reason FROM issues'):issues[identifier].append(reason)
    admission=sqlite3.connect(temporary)
    admission.executescript('CREATE TABLE images(id TEXT PRIMARY KEY,keep INTEGER,split TEXT,canonical_site TEXT,reasons TEXT); CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);')
    originals=Counter();retained=Counter();excluded=Counter();reasons=Counter()
    class_images=defaultdict(Counter);class_objects=defaultdict(Counter)
    admission_hash=hashlib.sha256();kept_ids=set();canonical_folds={}
    quarantine_temp=args.output/'quarantine.jsonl.partial'
    started=time.monotonic()
    with quarantine_temp.open('w',encoding='utf-8') as quarantine:
        for identifier,camera,site,split,objects in meta.execute('SELECT id,camera,site,split,objects FROM images ORDER BY id'):
            originals[split]+=1;policy=policies[site];why=list(issues.get(identifier,[]))
            if not policy['keep']:why.append('reviewed_cross_fold_background_component')
            keep=not why
            admission.execute('INSERT INTO images VALUES(?,?,?,?,?)',(identifier,int(keep),split,policy['canonical_site'],json.dumps(sorted(why))))
            admission_hash.update((identifier+'|'+str(int(keep))+'|'+split+'|'+policy['canonical_site']+'\n').encode())
            if keep:
                kept_ids.add(identifier);retained[split]+=1
                previous=canonical_folds.setdefault(policy['canonical_site'],split)
                if previous!=split:raise ValueError('Retained reviewed background component spans folds')
                for name,n in json.loads(objects).items():
                    if n:class_images[split][name]+=1;class_objects[split][name]+=n
            else:
                excluded[split]+=1;reasons.update(why)
                quarantine.write(json.dumps({'id':identifier,'camera':camera,'site':site,'split':split,'reasons':why},ensure_ascii=False)+'\n')
    unresolved=sum(a in kept_ids and b in kept_ids for a,b,*_ in pairs)
    if unresolved:raise ValueError('A known cross-fold candidate remains in retained data')
    digest=admission_hash.hexdigest()
    admission.executemany('INSERT INTO settings VALUES(?,?)',[('admission_sha256',digest),('reviewed_links_sha256',hashlib.sha256(links_bytes).hexdigest()),('policy','Original folds preserved; train > val > test only selects which existing rows to retain; no fold reassignment')])
    admission.commit();admission.close();temporary.replace(final);quarantine_temp.replace(args.output/'quarantine.jsonl')
    summary={'phase':'full_quality_review_completed_with_quarantine_overlay','automated_scans_completed':True,
             'admission_overlay_complete':True,'training_ready':False,
             'training_block_reason':'A training loader must honor this admission mask and a newly approved dataset identity; the old V4 dataset remains blocked. No model was trained or promoted by this review.',
             'processed_images':count,'preprocessing_rejected':states['preprocess'].get('rejected'),
             'original_split_counts':dict(originals),'retained_split_counts':dict(retained),'quarantined_split_counts':dict(excluded),
             'quarantine_reason_counts':dict(reasons),'retained_class_image_counts':{s:dict(c) for s,c in class_images.items()},
             'retained_class_object_counts':{s:dict(c) for s,c in class_objects.items()},
             'all_six_classes_present_in_each_retained_split':all(len(class_images[s])==6 for s in ['train','val','test']),
             'known_candidate_pairs_reviewed':len(pairs),'known_candidate_pairs_retained_across_folds':unresolved,
             'unused_review_links_with_no_exported_camera':unused,'admission_sha256':digest,
             'inventory_sha256':meta.execute("SELECT value FROM p.settings WHERE key='inventory_sha256'").fetchone()[0],
             'reviewed_links_sha256':hashlib.sha256(links_bytes).hexdigest(),
             'integrity_verified_images':states['integrity']['images_checked'],
             'derived_images_repaired':states['integrity']['repaired_images'],
             'policy':'No image changes folds; retained folds are subsets of the original ones. Visually reviewed connected components retain existing train rows before val before test. No model scores used.',
             'limitations':'Threshold-based similarity review is not proof of universal scene uniqueness or certified geographic separation. Old pilot metrics are not valid metrics for this filtered holdout.',
             'elapsed_seconds':round(time.monotonic()-started,1)}
    write_status(args.output/'status.json',summary)
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    meta.close();print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
