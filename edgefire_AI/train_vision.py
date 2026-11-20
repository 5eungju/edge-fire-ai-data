"""카메라 그룹으로 분리한 산불 영상 표본의 분할 모델 학습."""
import argparse, json, os, time, traceback, hashlib
from pathlib import Path
from datetime import datetime, timezone

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--data',default='E:/AI_Work/edgefire_vision/pilot_yolo_seg/dataset.yaml')
 parser.add_argument('--project',default='E:/AI_Work/edgefire_vision/training')
 parser.add_argument('--name',default='yolo26n_seg_pilot_01')
 parser.add_argument('--epochs',type=int,default=10)
 parser.add_argument('--imgsz',type=int,default=416)
 parser.add_argument('--batch',type=int,default=4)
 parser.add_argument('--threads',type=int,default=6)
 parser.add_argument('--weights',default='yolo26n-seg.pt')
 parser.add_argument('--baseline-metrics',type=Path)
 parser.add_argument('--comparison-output',type=Path)
 parser.add_argument('--resume',type=Path)
 parser.add_argument('--status',default='E:/AI_Work/edgefire_vision/training_status.json')
 args=parser.parse_args()
 os.environ['OMP_NUM_THREADS']=str(args.threads)
 os.environ['MKL_NUM_THREADS']=str(args.threads)
 os.environ['YOLO_AUTOINSTALL']='false'
 status_path=Path(args.status);status_path.parent.mkdir(parents=True,exist_ok=True)
 state={'pid':os.getpid(),'phase':'initializing','started_utc':datetime.now(timezone.utc).isoformat(),'config':vars(args)|{'resume':str(args.resume) if args.resume else None},'operationally_validated':False,'dataset_scope':'Camera-group split subset; not the entire 630000-image dataset'}
 def update(**values):
  state.update(values);state['updated_utc']=datetime.now(timezone.utc).isoformat()
  temporary=status_path.with_suffix('.tmp');temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2,default=str),encoding='utf8');temporary.replace(status_path)
 update()
 try:
  import torch, ultralytics
  from ultralytics import YOLO, settings
  torch.set_num_threads(args.threads)
  settings.update({k:False for k in ['sync','wandb','mlflow','comet','clearml'] if k in settings})
  data=Path(args.data).resolve()
  if not data.is_file():raise FileNotFoundError(data)
  manifest=data.parent.parent/'pilot_manifest.jsonl';groups={s:set() for s in ['train','val','test']};hashes=set();counts={s:0 for s in groups}
  for line in manifest.read_text(encoding='utf8').splitlines():
   row=json.loads(line);groups[row['split']].add(row['group_id']);counts[row['split']]+=1
   if row['raw_sha256'] in hashes:raise ValueError('Duplicate raw image')
   hashes.add(row['raw_sha256'])
  for a,b in [('train','val'),('train','test'),('val','test')]:
   if groups[a]&groups[b]:raise ValueError('Camera group leakage')
  if any(v==0 for v in counts.values()):raise ValueError('Empty split')
  update(phase='loading_pretrained_model',split_counts=counts,torch_version=torch.__version__,ultralytics_version=ultralytics.__version__,device='cpu',dataset_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
  model=YOLO(str(args.resume) if args.resume else args.weights)
  batch_number=[0];epoch_started=[time.monotonic()]
  def epoch_start(trainer):
   torch.set_num_threads(args.threads)
   batch_number[0]=0;epoch_started[0]=time.monotonic();update(phase='training',epoch=int(trainer.epoch)+1,epochs=int(trainer.epochs),batches_completed_in_epoch=0,run_directory=str(trainer.save_dir))
  def batch_end(trainer):
   batch_number[0]+=1
   if batch_number[0]==1 or batch_number[0]%10==0:
    update(phase='training',epoch=int(trainer.epoch)+1,batches_completed_in_epoch=batch_number[0],epoch_elapsed_seconds=round(time.monotonic()-epoch_started[0],1),loss={str(k):float(v) for k,v in trainer.tloss.items()} if isinstance(trainer.tloss,dict) else [float(v) for v in trainer.tloss.detach().cpu().flatten()])
  def epoch_end(trainer):
   update(phase='epoch_saved',completed_epochs=min(int(trainer.epoch)+1,int(trainer.epochs)),validation_metrics={k:float(v) for k,v in trainer.metrics.items()},last_checkpoint=str(trainer.last),best_checkpoint=str(trainer.best))
  model.add_callback('on_train_epoch_start',epoch_start);model.add_callback('on_train_batch_end',batch_end);model.add_callback('on_fit_epoch_end',epoch_end)
  kwargs={'resume':True} if args.resume else dict(data=str(data),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,device='cpu',workers=0,cache=False,amp=False,seed=42,deterministic=True,optimizer='AdamW',lr0=0.001,lrf=0.01,weight_decay=0.0005,patience=5,save=True,save_period=1,project=str(Path(args.project).resolve()),name=args.name,exist_ok=False,plots=True,verbose=False,close_mosaic=2,mosaic=0.5,mixup=0.0,degrees=0.0,flipud=0.0,fliplr=0.5)
  model.train(**kwargs)
  best=Path(model.trainer.best)
  if not best.is_file():raise RuntimeError('Training completed without best checkpoint')
  update(phase='evaluating_held_out_test',best_checkpoint=str(best))
  evaluator=YOLO(str(best));metrics=evaluator.val(data=str(data),split='test',imgsz=args.imgsz,batch=args.batch,device='cpu',workers=0,plots=True,project=str(Path(args.project).resolve()),name=args.name+'_heldout_test')
  result={'status':'completed','model':str(best),'split':'test','image_count':counts['test'],'metrics':{k:float(v) for k,v in metrics.results_dict.items()},'per_class':metrics.summary(),'operationally_validated':False,'limitations':['Pilot sample only; balanced collection sampling differs from deployment distribution.','Smoke/fire recognition is not a calibrated pre-ignition wildfire probability.','Official Training/Validation archives were regrouped by camera identifier.','Synthetic flame collection absent from validation; real flame is present.','Small distant smoke/flames require separate size-specific evaluation.','Previously inspected test is exploratory for subsequent runs, not a fresh blind test.']}
  (Path(model.trainer.save_dir)/'heldout_test_metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
  if args.baseline_metrics:
   baseline=json.loads(args.baseline_metrics.read_text(encoding='utf8'))
   comparison={'baseline_model':baseline['model'],'candidate_model':result['model'],'evaluation':'Same previously inspected test; exploratory comparison, not a fresh blind test.','metrics':{k:{'baseline':baseline['metrics'][k],'candidate':v,'difference':v-baseline['metrics'][k]} for k,v in result['metrics'].items() if k in baseline['metrics']},'per_class':result['per_class'],'operationally_validated':False}
   comparison_path=args.comparison_output or Path(model.trainer.save_dir)/'model_comparison.json'
   comparison_path.parent.mkdir(parents=True,exist_ok=True);comparison_path.write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf8')
  update(phase='completed',result=result)
 except BaseException as exc:
  update(phase='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=str(exc),traceback=traceback.format_exc());raise
if __name__=='__main__':main()
