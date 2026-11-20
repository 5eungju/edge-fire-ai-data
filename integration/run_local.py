"""로컬 개인 통합본 시작/상태/종료. 인증키는 SSD에만 저장합니다."""
import argparse, json, os, secrets, subprocess, sys, time
from pathlib import Path
import psutil, httpx

BASE=Path(__file__).resolve().parents[1]
DEFAULT_ROOT=Path('E:/AI_Work/edgefire_private_storage') if Path('E:/').exists() else BASE/'local_storage'
ROOT=Path(os.environ.get('EDGEFIRE_RUNTIME_ROOT',str(DEFAULT_ROOT))).resolve()

def configuration():
    ROOT.mkdir(parents=True,exist_ok=True)
    path=ROOT/'runtime.json'
    if not path.exists():
        path.write_text(json.dumps({'token':secrets.token_urlsafe(40),'storage_root':str(ROOT),
          'vision_model_path':str(BASE/'models/vision_pilot_v1.pt') if (BASE/'models/vision_pilot_v1.pt').exists() else 'E:/AI_Work/edgefire_vision/training/yolo26n_seg_pilot_01-2/weights/best.pt',
          'vision_model_id':'vision-pilot-v1','processes':{}},indent=2),encoding='utf8')
    return path,json.loads(path.read_text(encoding='utf8'))

def alive(pid,folder,command=None):
    try:
        process=psutil.Process(pid)
        return Path(process.cwd()).resolve()==folder.resolve() and process.is_running() and (command is None or all(part in process.cmdline() for part in command[1:]))
    except (psutil.NoSuchProcess,psutil.AccessDenied):
        return False

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','status','stop']);args=parser.parse_args()
    path,config=configuration();env=os.environ.copy()
    env.update({'LOCAL_API_TOKEN':config['token'],'STORAGE_ROOT':config['storage_root'],
      'VISION_MODEL_PATH':config['vision_model_path'],'VISION_MODEL_ID':config['vision_model_id'],
      'AI_BASE_URL':'http://127.0.0.1:8101','BACKEND_BASE_URL':'http://127.0.0.1:8100',
      'NEXT_TELEMETRY_DISABLED':'1','PYTHONUTF8':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','YOLO_AUTOINSTALL':'false'})
    training_status=Path(config.get('training_status_path',str(BASE.parents[1]/'outputs/vision_training_v2_status.json')))
    if training_status.is_file():env['TRAINING_STATUS_PATH']=str(training_status)
    for name,file in [('MODEL_PATH','environment_model.joblib'),('GAS_MODEL_PATH','gas_simulation.joblib'),('CHEMICAL_CATALOG_PATH','chemical_catalog.json')]:
        if (ROOT/'models'/file).is_file():env[name]=str(ROOT/'models'/file)
    services={
      'ai':(BASE/'edgefire_AI',[sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port','8101']),
      'backend':(BASE/'edgefire_back',[sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8100']),
      'frontend':(BASE/'edgefire_front',['node',str(BASE/'edgefire_front/node_modules/next/dist/bin/next'),'start','--hostname','127.0.0.1','--port','3100'])}
    for name,(folder,command) in services.items():
        pid=config.get('processes',{}).get(name,0)
        running=bool(pid and alive(pid,folder,command))
        if args.action=='stop' and running:
            process=psutil.Process(pid)
            for child in process.children(recursive=True):child.terminate()
            process.terminate();running=False
        if args.action=='start' and not running:
            logs=ROOT/'logs';logs.mkdir(exist_ok=True)
            with (logs/(name+'.log')).open('ab') as log:
                process=subprocess.Popen(command,cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,
                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            config.setdefault('processes',{})[name]=process.pid;running=True
        print(name,'RUNNING' if running else 'STOPPED')
    if args.action!='status':path.write_text(json.dumps(config,indent=2),encoding='utf8')
    if args.action=='start':
        for url in ['http://127.0.0.1:8101/api/v1/vision/info','http://127.0.0.1:8100/','http://127.0.0.1:3100/']:
            for _ in range(40):
                try:
                    response=httpx.get(url,timeout=3)
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(0.5)
            else:raise RuntimeError('서비스 시작 실패: '+url+'; SSD logs 폴더 확인')
        for name,(folder,command) in services.items():
            if not alive(config['processes'][name],folder,command):raise RuntimeError('실행 프로세스 확인 실패: '+name)
        print('화면: http://127.0.0.1:3100')
    if args.action=='status':
        try:
            response=httpx.get('http://127.0.0.1:8100/api/v1/storage/config',headers={'X-API-Key':config['token']},timeout=3)
            response.raise_for_status();print(json.dumps(response.json(),ensure_ascii=False,indent=2))
        except httpx.HTTPError:print('백엔드가 아직 준비되지 않았습니다.')

if __name__=='__main__':main()
