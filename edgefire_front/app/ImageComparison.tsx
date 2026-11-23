'use client';
import {useEffect,useState} from 'react';

const labels:Record<string,string>={black_smoke:'흑색 연기',white_gray_smoke:'백색·회색 연기',flame:'화염',cloud:'구름',fog_haze:'안개·연무',chimney_smoke:'굴뚝 연기'};
const describe=(items:string[])=>items.length ? items.map(item=>labels[item] || item).join(', ') : '없음';
type Case={id:string;primary_class:string;ground_truth_classes:string[];predicted_classes:string[];missed_classes:string[];extra_classes:string[];source_shard:string;model_id:string};

export default function ImageComparison({onClose}:{onClose:()=>void}){
  const [data,setData]=useState<{status:string;cases:Case[];model_id?:string}|null>(null);
  const [selected,setSelected]=useState(''),[error,setError]=useState('');
  useEffect(()=>{let active=true;const controller=new AbortController();
    fetch('/api/edgefire/vision-examples',{cache:'no-store',signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error('비교 자료 연결 실패');return response.json();})
      .then(value=>{if(active){setData(value);setSelected(value.cases?.[0]?.id || '');}})
      .catch(reason=>{if(active && reason.name!=='AbortError')setError(String(reason.message));});
    return()=>{active=false;controller.abort();};
  },[]);
  const item=data?.cases.find(value=>value.id===selected);
  return <div role="dialog" aria-label="검증 이미지 정답 예측 비교" aria-modal="true" className="fixed inset-0 z-[120] bg-black/90 p-4 overflow-y-auto text-white">
    <div className="max-w-6xl mx-auto bg-gray-900 border border-gray-600 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex justify-between gap-3"><h2 className="text-lg font-bold">검증 이미지 · 정답과 모델 예측 비교</h2><button onClick={onClose} className="bg-gray-700 px-3 py-1 rounded">비교 닫기</button></div>
      <p className="text-sm text-yellow-300">학습에 사용하지 않은 val 사례입니다. 실제 센서·실시간 CCTV·현재 지도 지역의 사진이 아닙니다. 소수 사례로 전체 정확도를 주장하지 않습니다.</p>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p>비교 자료를 읽는 중…</p>}
      {data?.status==='PREPARING' && <p>고정 모델의 검증 사례 비교를 준비 중입니다. 준비 후 다시 열어 주세요.</p>}
      {!!data?.cases.length && <label className="text-sm">비교할 사례 <select aria-label="비교할 사례" value={selected} onChange={event=>setSelected(event.target.value)} className="bg-gray-800 border border-gray-600 p-2 rounded max-w-full">
        {data.cases.map((value,index)=><option key={value.id} value={value.id}>{index+1}. {labels[value.primary_class]} · {value.id}</option>)}
      </select></label>}
      {item && <>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">{[['original','원본 이미지'],['ground-truth','데이터 정답 영역'],['prediction','고정 모델 예측']].map(([variant,title])=><figure key={variant} className="bg-black rounded p-2">
          <figcaption className="text-sm mb-2">{title}</figcaption><img src={`/api/edgefire/vision-examples/${item.id}/${variant}`} alt={title} className="w-full h-72 object-contain" />
        </figure>)}</div>
        <div className="text-sm grid gap-1"><p>정답: {describe(item.ground_truth_classes)}</p><p>예측: {describe(item.predicted_classes)}</p>
          <p className="text-orange-300">놓친 종류: {describe(item.missed_classes)} · 정답에 없는 검출: {describe(item.extra_classes)}</p>
          <p>위 비교는 종류의 유무이며, 박스·마스크 위치 정확도를 뜻하지 않습니다.</p>
          <p className="text-gray-400 break-all">출처: {item.source_shard} / images/val/{item.id}.jpg · labels/val/{item.id}.txt</p>
          <p className="text-gray-400 break-all">사용 모델: {item.model_id}</p>
        </div>
      </>}
    </div>
  </div>;
}
