'use client';
import {useEffect,useState} from 'react';
import './integration.css';
type Detection={class_name:string;score:number;polygon_normalized:number[][]};
type Job={id:string;status:string;created:number;error?:string;result?:{width:number;height:number;notice:string;model_id:string;detections:Detection[]}};
type Config={project_id:string;storage_id:string;owner_id:string;node_id:string;ai_model_available:boolean};
const labels:Record<string,string>={black_smoke:'흑색 연기',white_gray_smoke:'백색·회색 연기',flame:'화염',cloud:'구름',fog_haze:'안개·연무',chimney_smoke:'굴뚝 연기'};
const statuses:Record<string,string>={PENDING:'분석 대기',RUNNING:'분석 중',COMPLETED:'분석 완료',FAILED:'분석 실패'};
export default function Home(){
  const [config,setConfig]=useState<Config|null>(null),[jobs,setJobs]=useState<Job[]>([]),[selected,setSelected]=useState('');
  const [file,setFile]=useState<File|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [training,setTraining]=useState<{available:boolean;phase?:string;epoch?:number;epochs?:number;completed_epochs?:number;candidate_index?:number;candidate_total?:number}|null>(null);
  async function load(){
    fetch('/api/edgefire/training-status',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(setTraining).catch(()=>{});
    const response=await fetch('/api/edgefire/jobs',{cache:'no-store'});
    if(!response.ok)throw new Error('분석 기록을 가져올 수 없습니다. 서버 연결을 확인해 주세요.');
    setJobs(await response.json());
  }
  useEffect(()=>{let alive=true;
    fetch('/api/edgefire/config').then(async response=>{if(!response.ok)throw new Error('서버 연결을 확인해 주세요.');return response.json();}).then(value=>{if(alive)setConfig(value);}).catch(e=>{if(alive)setError(String(e.message));});
    const refresh=()=>load().catch(e=>{if(alive)setError(String(e.message));});refresh();
    const timer=setInterval(refresh,2500);return()=>{alive=false;clearInterval(timer);};
  },[]);
  async function upload(){if(!file)return;setBusy(true);setError('');
    try{const body=new FormData();body.append('image',file);const response=await fetch('/api/edgefire/jobs',{method:'POST',body});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'업로드를 확인해 주세요.');setSelected(data.id);await load();}
    catch(e){setError(e instanceof Error?e.message:'업로드 실패');}finally{setBusy(false);}}
  async function retry(id:string){setBusy(true);try{const response=await fetch('/api/edgefire/jobs/'+id+'/retry',{method:'POST'});if(!response.ok)throw new Error('재시도 요청 실패');await load();}catch(e){setError(String(e));}finally{setBusy(false);}}
  const active=jobs.find(job=>job.id===selected)||jobs[0];
  return <main className="ef"><header><div><p className="sub">EDGE-FIRE / PERSONAL WORKSPACE</p><h1>산불 영상 AI · 저장공간 연동</h1><p className="sub">이미지 저장부터 분석 기록까지 한 화면에서 확인합니다.</p></div><span className="pill">연구 시제품</span></header>
    {error&&<div className="error" role="alert">{error}</div>}
    <div className="grid"><aside><section className="panel"><h2>프로젝트 연결</h2><p className="sub">프로젝트 ID</p><p className="id">{config?.project_id||'연결 대기'}</p><p className="sub">카메라 장치 ID</p><p className="id">{config?.node_id||'연결 대기'}</p><p className="sub">저장공간 ID</p><p className="id">{config?.storage_id||'연결 대기'}</p><p className="sub">{config?.ai_model_available?'학습 완료 모델 연결됨':'모델 연결 확인 중'}</p></section>
    <section className="panel"><h2>이미지 분석</h2><p className="sub">JPEG · PNG · WEBP / 최대 10MiB</p><input type="file" accept="image/jpeg,image/png,image/webp" aria-label="분석할 이미지" onChange={event=>setFile(event.target.files?.[0]||null)}/><button disabled={!file||busy||!config} onClick={upload}>{busy?'저장 중…':'저장하고 분석하기'}</button><p className="sub" style={{marginTop:16}}>이미지와 분석 결과는 이 노트북의 SSD에 보관됩니다.</p></section>
    <section className="panel"><h2>모델 학습</h2><p className="sub">{training?.available ? (training.phase==='completed'?'학습 완료 · 성능 검토 대기':training.phase==='waiting_for_training'?`기존 학습 완료 대기 (${training.epoch||0}/${training.epochs||15})`:training.phase==='training_candidate'?`비교 ${training.candidate_index}/${training.candidate_total} · ${training.epoch||0}/${training.epochs||12} epoch`:training.phase==='evaluating_winner'?'선정 모델 시험 평가 중':['failed','interrupted','stopped','unknown'].includes(training.phase||'')?'학습 중단 또는 상태 확인 필요':`진행: ${training.epoch||0} / ${training.epochs||15} epoch`) : '별도 학습 상태 없음'}</p><p className="sub">현재 분석에는 완료된 첫 번째 모델을 사용합니다.</p></section><p className="sub"><a href="/team-demo">공유팀 관제 화면 시연 보기</a></p></aside>
    <section><div className="panel"><h2>분석 결과</h2>{!active?<div className="empty">아직 분석 기록이 없습니다.<br/>이미지를 업로드하면 결과가 여기에 표시됩니다.</div>:<><p className="sub">{statuses[active.status]||active.status} · {new Date(active.created*1000).toLocaleString('ko-KR')}</p><p className="id">{active.id}</p><div className="preview"><img src={'/api/edgefire/jobs/'+active.id+'/image'} alt="분석 원본"/>{active.result&&<svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="AI가 찾은 영역">{active.result.detections.map((item,index)=><polygon key={index} points={item.polygon_normalized.map(point=>point.join(',')).join(' ')} fill="rgba(255,140,70,.2)" stroke="#ffb15c" strokeWidth=".002"/>)}</svg>}</div>
    {active.status==='FAILED'&&<div className="error">분석에 실패했습니다. <button disabled={busy} onClick={()=>retry(active.id)}>다시 분석</button></div>}
    {active.result&&<><div className="notice">{active.result.notice}<br/>탐지된 객체가 없어도 안전하다는 의미는 아닙니다.</div><p className="sub">모델: {active.result.model_id}</p><table><thead><tr><th>객체</th><th>모델 분류 점수</th></tr></thead><tbody>{active.result.detections.length?active.result.detections.map((item,index)=><tr key={index}><td>{labels[item.class_name]||item.class_name}</td><td>{(item.score*100).toFixed(1)}%</td></tr>):<tr><td colSpan={2}>현재 기준에서 탐지된 객체 없음</td></tr>}</tbody></table></>}
    </>}</div><div className="panel"><h2>저장된 분석 기록</h2>{jobs.map(job=><button className="history" key={job.id} onClick={()=>setSelected(job.id)}>{statuses[job.status]||job.status} · {new Date(job.created*1000).toLocaleString('ko-KR')}<br/><small>{job.id}</small></button>)}</div></section></div></main>;
}
