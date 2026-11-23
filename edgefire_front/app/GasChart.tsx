"use client";
import {useEffect,useState} from 'react';
import {ResponsiveContainer,LineChart,Line,XAxis,YAxis,Tooltip,CartesianGrid,Legend} from 'recharts';

type Station={code:string;region:string;name:string;network:string};
type Observation={time:string;CO:number|null;NO2:number|null;SO2:number|null;O3:number|null;PM10:number|null;PM25:number|null};
type Series={status:string;rows:Observation[];forecast?:{status:string;CO_ppm?:number;target_time?:string};station?:Station};

export default function GasChart(_: {selectedSensorId:string}) {
  const [stations,setStations]=useState<Station[]>([]),[station,setStation]=useState('111121');
  const [area,setArea]=useState('서울'),[data,setData]=useState<Series|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;
    async function load(){try{
      const response=await fetch('/api/edgefire/air-quality/stations',{cache:'no-store'});
      if(!response.ok)throw new Error('대기측정 자료 연결 실패');
      const value=await response.json();if(!active)return;
      if(value.status!=='READY'){setError('새 측정자료 전처리·학습 중');timer=setTimeout(load,5000);return;}
      setStations(value.stations);setError('');
    }catch(reason){if(active)setError(String(reason));}}
    load();return()=>{active=false;clearTimeout(timer);};
  },[]);
  const visible=stations.filter(value=>value.region.startsWith(area));
  useEffect(()=>{if(visible.length && !visible.some(value=>value.code===station))setStation(visible[0].code);},[area,stations,station]);
  useEffect(()=>{if(!stations.length)return;let active=true;const controller=new AbortController();
    setLoading(true);setData(null);setError('');
    fetch('/api/edgefire/air-quality/series?station='+encodeURIComponent(station),{cache:'no-store',signal:controller.signal})
      .then(async response=>{const value=await response.json();if(!response.ok)throw new Error(value.detail || '측정값 조회 실패');return value;})
      .then(value=>{if(active){setData(value);setLoading(false);}})
      .catch(reason=>{if(active && reason.name!=='AbortError'){setError(String(reason.message));setLoading(false);}});
    return()=>{active=false;controller.abort();};
  },[station,stations]);
  return <div className="w-full h-full text-[10px] min-h-0 flex flex-col gap-1">
    <div className="flex gap-1"><select aria-label="대기측정 지역" value={area} onChange={event=>setArea(event.target.value)} className="bg-gray-900 rounded p-1">
      {['서울','경기','인천','강원'].map(value=><option key={value}>{value}</option>)}
    </select><select aria-label="대기 측정소" value={station} onChange={event=>setStation(event.target.value)} className="bg-gray-900 rounded p-1 min-w-0 flex-1">
      {visible.map(value=><option key={value.code} value={value.code}>{value.region} · {value.name}</option>)}
    </select></div>
    <p>2026년 과거 대기측정 · CO·NO₂ ppm · H₂ 자료 없음</p>
    {error && <p role="alert" className="text-yellow-300">{error}</p>}
    {loading && !error && <p>측정값 읽는 중…</p>}
    {data?.rows.length ? <>
      <p>{data.rows[0].time.replace('T',' ')} ~ {data.rows[data.rows.length-1].time.replace('T',' ')} KST</p>
      <div className="flex-1 min-h-[100px]"><ResponsiveContainer width="100%" height="100%" minWidth={60} minHeight={100}>
        <LineChart data={data.rows} margin={{top:5,right:0,left:-25,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151"/><XAxis dataKey="time" tickFormatter={value=>String(value).slice(11)} stroke="#9CA3AF" minTickGap={25}/>
          <YAxis yAxisId="co" stroke="#EF4444" domain={['auto','auto']}/><YAxis yAxisId="no2" orientation="right" stroke="#3B82F6" width={35}/>
          <Tooltip contentStyle={{backgroundColor:'#1F2937',borderColor:'#374151',color:'#FFF'}}/><Legend/>
          <Line yAxisId="co" type="linear" dataKey="CO" name="CO ppm" stroke="#EF4444" strokeWidth={2} dot={false} connectNulls={false}/>
          <Line yAxisId="no2" type="linear" dataKey="NO2" name="NO₂ ppm" stroke="#3B82F6" strokeWidth={2} dot={false} connectNulls={false}/>
        </LineChart>
      </ResponsiveContainer></div>
      {data.forecast?.status==='RESEARCH_FORECAST' ? <p className="text-blue-200">다음 시간 CO 추정: {data.forecast.CO_ppm?.toFixed(3)} ppm ({data.forecast.target_time?.replace('T',' ')})</p> : <p>CO 추정: {data.forecast?.status==='REJECTED_FAILED_PERSISTENCE_BASELINE' ? '기준선 미달로 출력 보류' : '연속 측정 이력 부족'}</p>}
      <p className="text-gray-400">장비·지도와 별도인 과거 자료 · 산불 판정값 아님</p>
    </> : !loading && !error ? <p>이 측정소의 자료가 없습니다.</p> : null}
  </div>;
}
