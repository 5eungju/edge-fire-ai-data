"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import GasChart from "./GasChart";
import ImageComparison from "./ImageComparison";
import regionCatalog from "../../edgefire_AI/fire_forecast/regions.json";
import { RISK_LEVELS, type RiskLevel } from "./riskLevels";

const CesiumMap = dynamic(() => import("./CesiumMap"), { ssr: false });

export default function Home() {
  const regionNames:Record<string,string> = {...Object.fromEntries(regionCatalog.map(region=>[region.id,region.name])),map:'지도 선택 지점'};
  const [photoRegion,setPhotoRegion] = useState('seoul');
  const [showUnassigned,setShowUnassigned] = useState(false);
  const [photoRevision,setPhotoRevision] = useState(0);
  const photoScopeRef = useRef('seoul');
  photoScopeRef.current = showUnassigned ? 'unassigned' : photoRegion;
  const photoRequestRef = useRef(0);
  const mapRef = useRef<any>(null);
  const photoInputRef = useRef<HTMLInputElement>(null);
  const submittedImageRef = useRef('');
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState('');

  // 선택된 센서 및 실시간 관제 상태 관리
  const [selectedSensorId, setSelectedSensorId] = useState<string>("GAS-Node-02");
  const [showAlertModal, setShowAlertModal] = useState<boolean>(false);
  const [alertMessage, setAlertMessage] = useState<string>("");
  const [isThermal, setIsThermal] = useState<boolean>(false);
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [emergencyStatus, setEmergencyStatus] = useState<string>("● 시스템 상태: 정상");
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [actionPopup, setActionPopup] = useState<string | null>(null);
  const [showDetectionCompare, setShowDetectionCompare] = useState(false);
  const [showImageComparison, setShowImageComparison] = useState(false);
  // 센서별 위험 단계 (현재는 화면 테스트용 초기값)
const [sensorRiskLevels] = useState<
  Record<string, RiskLevel>
>({
  "WUI-A": 3,
  "WUI-B": 1,
  "GAS-Node-01": 1,
  "GAS-Node-02": 4,
});

// 위험 단계별 배지 스타일
const riskBadgeStyles: Record<RiskLevel, string> = {
  1: "bg-green-900 text-green-300",
  2: "bg-blue-900 text-blue-300",
  3: "bg-yellow-900 text-yellow-300",
  4: "bg-orange-900 text-orange-300",
  5: "bg-red-900 text-red-300",
};

  const [storageJob, setStorageJob] = useState<any>(null);
  const currentPhotoRef = useRef<any>(null);currentPhotoRef.current=storageJob;
  const [storageConnected, setStorageConnected] = useState(false);
  const [chemicalCid, setChemicalCid] = useState('');
  const [useReferenceCase, setUseReferenceCase] = useState(false);
  const [assessmentId, setAssessmentId] = useState('');
  const [assessmentResult, setAssessmentResult] = useState<any>(null);
  const [assessmentError, setAssessmentError] = useState('');
  const [assessmentBusy, setAssessmentBusy] = useState(false);
  useEffect(() => {
    if (!assessmentId) return;
    let active = true;
    const poll = async () => {
      try {
        const response = await fetch(`/api/edgefire/assessments/${assessmentId}`, {cache:'no-store'});
        if (!response.ok) throw new Error('통합 분석 결과를 읽을 수 없습니다.');
        const job = await response.json();
        if (!active) return;
        if (job.status === 'COMPLETED') { setAssessmentResult(job.result); setAssessmentBusy(false); setAssessmentId(''); }
        if (job.status === 'FAILED') { setAssessmentError(job.error || '분석 실패'); setAssessmentBusy(false); setAssessmentId(''); }
      } catch (error) { if (active) { setAssessmentError(String(error)); setAssessmentBusy(false); } }
    };
    poll(); const timer = setInterval(poll, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [assessmentId]);
  async function runAssessment() {
    const visionId=storageJob?.id;
    if(!visionId) return;
    setAssessmentBusy(true); setAssessmentError(''); setAssessmentResult(null); setAssessmentId('');
    try {
      const payload:any = {vision_job_id:visionId};
      if (chemicalCid.trim()) payload.chemical_cid = chemicalCid.trim();
      if (useReferenceCase) {
        const response = await fetch('/api/edgefire/model-examples', {cache:'no-store'});
        if (!response.ok) throw new Error('학습 사례를 읽을 수 없습니다.');
        const examples = await response.json();
        if (!examples.cases?.length) throw new Error('등록된 학습 사례가 없습니다.');
        payload.reference_case_id = examples.cases[0].id;
        if (!payload.chemical_cid && examples.chemical_cids?.length) payload.chemical_cid = examples.chemical_cids[0];
      }
      const response = await fetch('/api/edgefire/assessments', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const job = await response.json();
      if (!response.ok) throw new Error(job.detail || '통합 분석을 시작할 수 없습니다.');
      if(currentPhotoRef.current?.id===visionId) setAssessmentId(job.id);
    } catch (error) { if(currentPhotoRef.current?.id===visionId) {setAssessmentError(String(error)); setAssessmentBusy(false);} }
  }
  useEffect(() => {
    let active = true;
    const scope = showUnassigned ? 'unassigned' : photoRegion;
    submittedImageRef.current='';setStorageJob(null);setPhotoBusy(false);setPhotoError('');
    setAssessmentId('');setAssessmentResult(null);setAssessmentBusy(false);setShowAlertModal(false);
    async function refresh() {
      try {
        if (scope === 'map') return;
        const sequence = ++photoRequestRef.current;
        const response = await fetch(`/api/edgefire/jobs?region=${scope}`, {cache: 'no-store'});
        if (!response.ok) throw new Error('Storage unavailable');
        const jobs = await response.json();
        if (active && sequence === photoRequestRef.current && photoScopeRef.current === scope) {
          setStorageConnected(true);
          const selected = submittedImageRef.current ? jobs.find((job:any) => job.id === submittedImageRef.current) : jobs[0];
          setStorageJob(selected || null);
          if (selected && ['COMPLETED','FAILED'].includes(selected.status)) {
            setPhotoBusy(false);
            if (selected.status === 'FAILED') setPhotoError(selected.error || '사진 분석 실패');
          }
        }
      } catch { if (active) setStorageConnected(false); }
    }
    refresh();
    const timer = setInterval(refresh, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [photoRegion,showUnassigned,photoRevision]);

  function changePhotoRegion(id:string) {
    photoScopeRef.current=id;++photoRequestRef.current;submittedImageRef.current='';
    setStorageJob(null);setPhotoRegion(id);setShowUnassigned(false);setPhotoBusy(false);
  }
  async function connectPhoto() {
    if (!storageJob || photoRegion === 'map') return;
    const region=photoRegion, scope=photoScopeRef.current;
    setPhotoError('');
    try {
      const response=await fetch(`/api/edgefire/jobs/${storageJob.id}/location`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({region_id:region})});
      const data=await response.json();if(!response.ok) throw new Error(data.detail || '지역 연결 실패');
      if(photoScopeRef.current===scope) {setShowUnassigned(false);setPhotoRevision(n=>n+1);}
    } catch(error) {if(photoScopeRef.current===scope) setPhotoError(String(error));}
  }

  async function uploadPhoto(file: File) {
    const region=photoRegion;
    if(region==='map' || showUnassigned) {setPhotoError('지도에서 등록 지역을 선택한 뒤 사진을 입력해 주세요.');return;}
    ++photoRequestRef.current;
    setPhotoError('');
    if (file.size > 10*1024*1024) { setPhotoError('사진은 10MiB 이하로 선택해 주세요.'); return; }
    setPhotoBusy(true);setAssessmentResult(null);setAssessmentId('');setAssessmentBusy(false);
    try {
      const body = new FormData();body.append('image',file);body.append('region_id',region);
      const response = await fetch('/api/edgefire/jobs',{method:'POST',body});
      const job = await response.json();
      if (!response.ok) throw new Error(job.detail || '사진을 저장할 수 없습니다.');
      if(photoScopeRef.current===region) {++photoRequestRef.current;submittedImageRef.current=job.id;setStorageJob(job);}
    } catch (error) { if(photoScopeRef.current===region) {setPhotoError(String(error));setPhotoBusy(false);} }
  }

  const handleSensorClick = (sensorId: string) => {
    setSelectedSensorId(sensorId);
    if (mapRef.current) {
      mapRef.current.flyToSensor(sensorId);
    }
    if (sensorId === "CAM-PTZ-01" && storageJob?.status === 'COMPLETED') {
      const detections = storageJob.result?.detections || [];
      setAlertMessage(detections.length
        ? detections.map((d: any) => `${d.class_name}: ${(d.score * 100).toFixed(1)}%`).join(', ')
        : '저장된 이미지에서 검출 결과가 없습니다.');
      setShowAlertModal(true);
    }
  };

  const handleEmergencyAction = (type: string) => {
    let msg = "";
    if (type === "119") msg = "🚨 [119 긴급 신고] 119 긴급 전파 시연 요청이 접수되었습니다. 실제 신고는 전송되지 않았습니다.";
    if (type === "BROADCAST") msg = "📢 [마을 방송] 마을 방송 발령 시연 요청이 접수되었습니다. 실제 방송은 송출되지 않았습니다.";
    if (type === "CBS") msg = "📱 [재난문자] 재난문자 및 알림톡 발송 시연 요청이 접수되었습니다. 실제 메시지는 발송되지 않았습니다.";

    setLastAction(msg);
    setEmergencyStatus("🚨 비상 경보 시연 중");
    setActionPopup(msg);
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-gray-900 text-white p-2 gap-2 box-border relative">
      {showImageComparison && <ImageComparison onClose={() => setShowImageComparison(false)} />}
      {/* 비상 경보 시연 알림 팝업 */}
{actionPopup && (
  <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="w-[420px] max-w-[90vw] rounded-xl border border-gray-600 bg-gray-800 p-6 shadow-2xl">

      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-green-500/15 text-green-400 text-xl">
          ✓
        </div>

        <h2 className="text-lg font-semibold text-white">
          비상 경보 시연 알림
        </h2>
      </div>

      <p className="mb-6 text-sm leading-relaxed text-gray-300">
        {actionPopup}
      </p>

      <div className="flex justify-end">
        <button
          onClick={() => setActionPopup(null)}
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-blue-500"
        >
          확인
        </button>
      </div>

    </div>
  </div>
)}
      {/* 1차·2차 감지 비교: 시연용 데이터 (실제 감지 이력 아님) */}
      {showDetectionCompare && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={() => setShowDetectionCompare(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="detection-compare-title"
            className="w-full max-w-2xl rounded-xl border border-gray-600 bg-gray-900 p-5 shadow-2xl max-h-[90vh] overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-gray-700 pb-3">
              <div>
                <h2 id="detection-compare-title" className="text-lg font-bold text-white">🔎 1차·2차 감지 비교</h2>
                <p className="mt-1 text-xs text-gray-400">GAS-Node-02 · 시연용 예시 데이터 (실제 센서 수신 기록 아님)</p>
              </div>
              <button type="button" onClick={() => setShowDetectionCompare(false)} className="rounded px-2 py-1 text-gray-300 hover:bg-gray-700" aria-label="비교 창 닫기">✕</button>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-yellow-700/70 bg-gray-800 p-4">
                <div className="flex items-center justify-between gap-2"><h3 className="font-semibold text-yellow-300">① 1차 감지</h3><span className="rounded bg-yellow-900 px-2 py-1 text-xs text-yellow-200">3단계 · 주의</span></div>
                <p className="mt-2 text-xs text-gray-400">시연 시각 14:05</p>
                <p className="mt-3 text-sm text-gray-200">CO <strong className="text-white">45 ppm</strong></p>
                <p className="mt-1 text-sm text-gray-200">H₂ <strong className="text-white">20 ppm</strong></p>
                <p className="mt-3 text-xs text-gray-400">가스 농도 상승 감지 (예시)</p>
              </div>
              <div className="rounded-lg border border-orange-600/70 bg-gray-800 p-4">
                <div className="flex items-center justify-between gap-2"><h3 className="font-semibold text-orange-300">② 2차 감지</h3><span className="rounded bg-orange-900 px-2 py-1 text-xs text-orange-200">4단계 · 경계</span></div>
                <p className="mt-2 text-xs text-gray-400">시연 시각 14:10</p>
                <p className="mt-3 text-sm text-gray-200">CO <strong className="text-white">85 ppm</strong></p>
                <p className="mt-1 text-sm text-gray-200">H₂ <strong className="text-white">38 ppm</strong></p>
                <p className="mt-3 text-xs text-gray-400">추가 상승 확인 (예시)</p>
              </div>
            </div>
            <div className="mt-3 rounded-lg border border-gray-700 bg-gray-800 p-4">
              <h3 className="mb-3 text-sm font-semibold text-white">📈 1차 대비 2차 변화</h3>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div><p className="text-xs text-gray-400">경과 시간</p><p className="mt-1 font-bold">5분</p></div>
                <div><p className="text-xs text-gray-400">CO 변화</p><p className="mt-1 font-bold text-orange-300">+40 ppm</p></div>
                <div><p className="text-xs text-gray-400">H₂ 변화</p><p className="mt-1 font-bold text-orange-300">+18 ppm</p></div>
                <div><p className="text-xs text-gray-400">위험 단계</p><p className="mt-1 font-bold text-orange-300">3 → 4단계</p></div>
              </div>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-gray-400">※ 수치·시간·단계는 UI 검증을 위한 예시입니다. 실제 1차·2차 감지의 정의와 판정 기준, 수신 데이터 형식은 백엔드/AI 팀과 협의 후 연동해야 합니다.</p>
            <div className="mt-4 flex justify-end"><button type="button" onClick={() => setShowDetectionCompare(false)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold hover:bg-blue-500">확인</button></div>
          </section>
        </div>
      )}
      {/* 🚨 AI 화재 확증 팝업 모달 */}
      {showAlertModal && (
        <div className="absolute inset-0 bg-black/70 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-gray-900 border-2 border-red-500 rounded-xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-gray-700 pb-2">
              <h3 className="text-lg font-bold text-red-500 flex items-center gap-2">
                AI 저장 이미지 분석 결과
              </h3>
              <button onClick={() => setShowAlertModal(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <p className="text-sm text-gray-200 leading-relaxed">{alertMessage}</p>
            <button onClick={() => setShowImageComparison(true)} className="bg-blue-800 rounded p-2 text-sm">화재·비화재 이미지 정답과 예측 비교</button>
            <div className="bg-gray-800 p-3 rounded border border-gray-700 text-xs text-orange-400">
              • 모델: {storageJob?.result?.model_id || "대기 중"}<br />
              • 학습 중 모델입니다. 위험 단계는 시연값이며 대기 차트는 과거 관측 자료입니다.
            </div>
            <div className="text-xs text-gray-200 flex flex-col gap-2">
              <label>화학물질 CID (알고 있는 경우)
                <input aria-label="화학물질 CID" value={chemicalCid} onChange={event => setChemicalCid(event.target.value)} className="ml-2 w-28 bg-gray-800 border border-gray-600 rounded p-1" />
              </label>
              <label className="flex gap-2 items-center"><input type="checkbox" checked={useReferenceCase} onChange={event => setUseReferenceCase(event.target.checked)} />학습 데이터 예시로 연결 시험 (현재 이미지와 다른 사건)</label>
              <button onClick={runAssessment} disabled={assessmentBusy} className="bg-blue-700 disabled:opacity-50 rounded p-2">{assessmentBusy ? '저장소에서 통합 분석 중…' : '저장소 통합 분석'}</button>
              {assessmentError && <p className="text-red-300">{assessmentError}</p>}
              {assessmentResult && <div className="bg-gray-800 p-2 rounded flex flex-col gap-2">
                <p>{assessmentResult.input_kind === 'historical_training_case' ? '학습 사례 시험 결과 · 실제 현장 판단 아님' : '입력 정보 기준 연구용 결과'}</p>
                <p>대응 모델: {assessmentResult.response?.status === 'INSUFFICIENT_INPUT' ? '기상·지형·화재 상태 등 추가 입력 필요' : assessmentResult.response?.status === 'REJECTED_FAILED_VALIDATION_BASELINE' ? '검증 기준선 미달로 위험도 출력 차단' : `데이터 주석 위험도 ${assessmentResult.response?.annotated_risk}`}</p>
                <p>화학 분석: {assessmentResult.chemical?.status === 'NO_MATERIAL_ID' ? '물질 CID 미입력' : assessmentResult.chemical?.name}</p>
                {Object.entries(assessmentResult.chemical?.predictions || {}).map(([name,value]:[string,any]) => <p key={name}>{name}: {typeof value.value === 'number' ? value.value.toFixed(3) : value.status} {value.target_transform === 'log10' ? '(log10)' : ''} · 원자료 단위 미검증</p>)}
                {assessmentResult.historical_references?.slice(0,1).map((reference:any) => <div key={reference.id}>
                  <p>과거 대응 사례 인용 ({reference.event_id}): {reference.recommendation.decision}</p>
                  <p>{reference.recommendation.primary_reason}</p>
                  <details><summary>데이터 출처</summary><p className="break-all">{reference.source} · {reference.member}</p></details>
                </div>)}
                <p>가스·열화상 측정값 없음 · 자동 신고·방송은 실행하지 않음</p>
              </div>}
            </div>
            <div className="flex gap-2 justify-end mt-2">
              <button onClick={() => setShowAlertModal(false)} className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded text-xs">닫기</button>
              <button onClick={() => { setShowAlertModal(false); handleEmergencyAction("BROADCAST"); }} className="bg-red-600 hover:bg-red-700 px-4 py-2 rounded text-xs font-bold text-white">즉시 비상 방송 발령</button>
            </div>
          </div>
        </div>
      )}

      {/* 1. 상단바 (Header) */}
      <header className="h-14 bg-gray-800 rounded-lg flex items-center justify-between px-6 border border-gray-700">
        <h1 className="text-xl font-bold text-red-500">
          🔥 [EDGE-FIRE] AIoT 산불 조기감지 통합 관제 시스템
        </h1>
        <div className="flex gap-4 text-sm text-gray-300 items-center">
          <span>저장소: {storageConnected ? "연결됨" : "연결 대기"} · 센서 시연</span>
          <span className={emergencyStatus.includes("정상") ? "text-green-400" : "text-red-400 font-bold animate-pulse"}>
            {emergencyStatus}
          </span>
        </div>
      </header>

      {/* 2. 메인 관제 영역 */}
      <div className="flex flex-1 gap-2 overflow-hidden">
        {/* 좌측 패널: 위험 구역 & 센서 리스트 */}
        <aside className="w-[20%] bg-gray-800 rounded-lg p-4 border border-gray-700 flex flex-col gap-2">
          <h2 className="font-bold text-lg border-b border-gray-700 pb-2">■ WUI 위험 구역 & 센서</h2>
          <div className="text-xs text-gray-400 mb-1">💡 센서를 클릭하면 해당 위치로 이동합니다.</div>
          <ul className="text-sm space-y-2 text-gray-300">
            {([
              { id: "WUI-A", name: "📍 WUI A구역" },
              { id: "WUI-B", name: "📍 WUI B구역" },
              { id: "GAS-Node-01", name: "🔥 [가스] GAS-Node-01" },
              { id: "GAS-Node-02", name: "🔥 [가스] GAS-Node-02" },
            ] as const).map(({ id, name }) => {
              const level = sensorRiskLevels[id];
              return (
                <li
                  key={id}
                  onClick={() => handleSensorClick(id)}
                  className={`p-2 rounded cursor-pointer transition flex items-center justify-between gap-2 ${
                    selectedSensorId === id
                      ? "bg-gray-600 border border-blue-400 font-bold"
                      : "bg-gray-700 hover:bg-gray-600"
                  }`}
                >
                  <span className="min-w-0 truncate">{name}</span>
                  <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded ${riskBadgeStyles[level]}`}>
                    {level}단계 · {RISK_LEVELS[level].label}
                  </span>
                </li>
              );
            })}
            <li
              onClick={() => handleSensorClick("CAM-PTZ-01")}
              className={`p-2 rounded cursor-pointer transition flex items-center justify-between ${
                selectedSensorId === "CAM-PTZ-01"
                  ? "bg-blue-900/60 border border-blue-500 font-bold"
                  : "bg-gray-700 hover:bg-gray-600"
              }`}
            >
              <span>📷 [카메라] CAM-PTZ-01</span>
              <span className="text-xs bg-blue-900 text-blue-300 px-1.5 py-0.5 rounded">ON</span>
            </li>
          </ul>

          <button
            type="button"
            onClick={() => setShowDetectionCompare(true)}
            className="mt-2 w-full rounded-lg border border-blue-500/60 bg-blue-900/40 px-3 py-2.5 text-sm font-semibold text-blue-100 transition hover:bg-blue-800/60"
          >
            🔎 1차·2차 감지 비교 보기
          </button>

          {lastAction && (
            <div className="mt-auto p-2.5 bg-red-950/80 border border-red-700/80 rounded text-[11px] text-red-200">
              <p className="font-bold text-red-400 mb-1">📢 최근 제어 이력</p>
              <p className="line-clamp-2">{lastAction}</p>
            </div>
          )}
        </aside>

        {/* 중앙 패널: 3D GIS 관제 지도 */}
        <main className="w-[55%] bg-gray-950 rounded-lg border border-gray-700 relative overflow-hidden">
          <CesiumMap enableForecast={true} onRegionChange={changePhotoRegion} ref={mapRef} />
        </main>

        {/* 우측 패널: 실시간 차트 및 PTZ 비디오 */}
        <aside className="w-[25%] flex flex-col gap-2">
          <div className="h-1/2 bg-gray-800 rounded-lg p-4 border border-gray-700 flex flex-col">
            <h2 className="font-bold border-b border-gray-700 pb-2 text-sm text-gray-200 flex justify-between items-center">
              <span>■ 과거 대기측정 농도 · 2026년</span>
              <span className="text-xs text-yellow-400">관측소 자료</span>
            </h2>
            <div className="flex-1 w-full h-full pt-3">
              <GasChart selectedSensorId={selectedSensorId} />
            </div>
          </div>

          <div className="h-1/2 bg-gray-800 rounded-lg p-4 border border-gray-700 flex flex-col">
            <h2 className="font-bold border-b border-gray-700 pb-2 text-sm text-gray-200 flex justify-between items-center">
              <span>■ 저장 사진 · {showUnassigned ? '지역 미지정' : regionNames[photoRegion]}</span>
              <button onClick={() => photoInputRef.current?.click()} disabled={photoBusy || showUnassigned || photoRegion==='map'} className="text-xs bg-blue-700 disabled:opacity-50 text-white px-2 py-1 rounded">{photoBusy ? '사진 분석 중…' : '사진 입력'}</button>
              <input ref={photoInputRef} type="file" accept="image/jpeg,image/png,image/webp" aria-label="분석할 사진" className="hidden" onChange={event => {const file=event.target.files?.[0];if(file) uploadPhoto(file);event.target.value='';}} />
            </h2>
            <div className="flex gap-2 text-[10px] pt-1">
              <button onClick={()=>{++photoRequestRef.current;photoScopeRef.current=showUnassigned?photoRegion:'unassigned';setStorageJob(null);setShowUnassigned(!showUnassigned);}} className="underline">{showUnassigned?'지역 사진으로 돌아가기':'미지정 사진 보기'}</button>
              {showUnassigned && storageJob && photoRegion!=='map' && <button onClick={connectPhoto} className="text-blue-300 underline">{regionNames[photoRegion]}에 연결</button>}
            </div>
            <div className="flex-1 min-h-0 w-full pt-2 flex flex-col justify-center items-center relative overflow-hidden rounded bg-black mt-2 border border-gray-700">
              {storageJob ? <img
                src={`/api/edgefire/jobs/${storageJob.id}/${storageJob.status === 'COMPLETED' ? 'annotated' : 'image'}`}
                alt={storageJob.status === 'COMPLETED' ? '저장소 AI 분석 결과' : '분석 대기 중인 입력 사진'}
                style={{ transform: `scale(${zoomLevel})` }}
                className="w-full h-full object-contain transition-all duration-300"
              /> : <p className="text-xs text-gray-300 p-4">{photoRegion==='map' ? '사진 연결은 지도 지역 목록에서 등록 지역을 선택해 주세요.' : '이 지역에 연결된 사진이 없습니다. 사진 입력으로 저장하거나 미지정 사진을 연결해 주세요.'}</p>}
              <div className="absolute top-2 left-2 bg-black/60 text-white text-[10px] px-2 py-1 rounded backdrop-blur">
                {storageJob ? `${submittedImageRef.current ? '입력 사진' : '저장 이미지'} · ${storageJob.status === 'COMPLETED' ? '분석 완료' : storageJob.status === 'FAILED' ? '분석 실패' : '분석 대기/진행'} · ${storageJob.region_id ? regionNames[storageJob.region_id]+' (사용자 지정)' : '지역 미지정'} | 표시 효과:` : "사진 대기 | 표시 효과:"} {isThermal ? "🔥 IR Thermal" : "📷 Visible"} | Zoom: {zoomLevel}x
              </div>
              {photoError && <p role="alert" className="absolute top-14 left-2 right-2 bg-red-950/95 text-red-200 text-xs p-2 rounded">{photoError}</p>}
              <div className="absolute bottom-2 right-2 bg-black/70 p-1.5 rounded-lg border border-gray-700 flex gap-1 backdrop-blur">
                <button onClick={() => setZoomLevel((prev) => Math.min(prev + 0.5, 3))} className="bg-gray-700 text-[10px] px-2 py-1 rounded font-bold">🔍 +</button>
                <button onClick={() => setZoomLevel((prev) => Math.max(prev - 0.5, 1))} className="bg-gray-700 text-[10px] px-2 py-1 rounded font-bold">🔍 -</button>
                <button onClick={() => setIsThermal(!isThermal)} className={`text-[10px] px-2 py-1 rounded font-bold ${isThermal ? "bg-red-600 text-white" : "bg-gray-700"}`}>🔥 IR 열화상</button>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* 3. 하단 비상 경보 전파 제어반 */}
      <footer className="h-16 bg-gray-800 rounded-lg flex items-center justify-around border border-gray-700 px-4">
        <button onClick={() => handleEmergencyAction("119")} className="bg-red-600 hover:bg-red-700 text-white font-bold py-2.5 px-6 rounded-lg transition active:scale-95">🚨 119 긴급 전파</button>
        <button onClick={() => handleEmergencyAction("BROADCAST")} className="bg-orange-600 hover:bg-orange-700 text-white font-bold py-2.5 px-6 rounded-lg transition active:scale-95">📢 마을 방송 IP Relay 발령</button>
        <button onClick={() => handleEmergencyAction("CBS")} className="bg-yellow-600 hover:bg-yellow-700 text-white font-bold py-2.5 px-6 rounded-lg transition active:scale-95">📱 긴급재난문자 / 알림톡 발송</button>
      </footer>
    </div>
  );
}
