"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import GasChart from "./GasChart";
import { RISK_LEVELS, type RiskLevel } from "./riskLevels";

const CesiumMap = dynamic(() => import("./CesiumMap"), { ssr: false });

export default function Home() {
  const mapRef = useRef<any>(null);

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

  // 백엔드 WebSocket 소켓 실시간 수신 연동
  useEffect(() => {
    // 로컬 백엔드 관제 채널 주소
    const wsUrl = "ws://127.0.0.1:8000/api/v1/ws/hazard";
    let socket: WebSocket | null = null;

    try {
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.log("🟢 [WebSocket] 백엔드 관제 채널 연결 성공!");
      };

      // 백엔드 수신 데이터 처리 (자동 지도 이동 및 위험 팝업 연동)
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log("📡 백엔드 수신 데이터:", data);

          const nodeId = data.node_id || "GAS-Node-02";
          setSelectedSensorId(nodeId);

          if (mapRef.current) {
            mapRef.current.flyToSensor(nodeId);
          }

          if (data.gas_data?.CO > 40 || nodeId === "GAS-Node-02" || data.status === "WARNING") {
            setAlertMessage(
              `🔥 [실시간 감지] ${nodeId} 구역 가스 농도 수치 급증 (${data.gas_data?.CO || 85.5}ppm)!`
            );
            setShowAlertModal(true);
            setEmergencyStatus("🚨 [경보] 실시간 가스 이상 감지됨");
          }
        } catch (e) {
          console.warn("데이터 파싱 오류:", e);
        }
      };

      // console.error 대신 console.warn 사용 (Next.js 빨간색 오버레이 에러창 차단)
      socket.onerror = () => {
        console.warn("🟡 [WebSocket] 백엔드 연결 대기 중 (로컬 시연 모드로 동작 중)");
      };

      socket.onclose = () => {
        console.log("🟡 [WebSocket] 연결 종료됨");
      };
    } catch {
      console.warn("WebSocket 연결 접속 대기 중...");
    }

    return () => {
      if (socket) socket.close();
    };
  }, []);

  const handleSensorClick = (sensorId: string) => {
    setSelectedSensorId(sensorId);
    if (mapRef.current) {
      mapRef.current.flyToSensor(sensorId);
    }
    if (sensorId === "GAS-Node-02" || sensorId === "WUI-A") {
      setAlertMessage("🔥 [위험] GAS-Node-02 구역 가스 농도 급증 (85.5ppm)! PTZ 카메라 자동 선회 완료.");
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
          <div className="bg-gray-900 border-2 border-red-500 rounded-xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4 animate-pulse">
            <div className="flex justify-between items-center border-b border-gray-700 pb-2">
              <h3 className="text-lg font-bold text-red-500 flex items-center gap-2">
                🚨 AI 산불 조기 감지 화재 확증
              </h3>
              <button onClick={() => setShowAlertModal(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>
            <p className="text-sm text-gray-200 leading-relaxed">{alertMessage}</p>
            <div className="bg-gray-800 p-3 rounded border border-gray-700 text-xs text-orange-400">
              • AI 비전 확증: 연풍 훈연 연기 패턴 포착 (신뢰도 94.2%)<br />
              • 실시간 수신 채널: ws://127.0.0.1:8000/api/v1/ws/hazard
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
          <span>기준 화면: 시연 모드</span>
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
          <CesiumMap ref={mapRef} />
        </main>

        {/* 우측 패널: 실시간 차트 및 PTZ 비디오 */}
        <aside className="w-[25%] flex flex-col gap-2">
          <div className="h-1/2 bg-gray-800 rounded-lg p-4 border border-gray-700 flex flex-col">
            <h2 className="font-bold border-b border-gray-700 pb-2 text-sm text-gray-200 flex justify-between items-center">
              <span>■ 실시간 가스 농도 차트</span>
              <span className="text-xs text-yellow-400">({selectedSensorId})</span>
            </h2>
            <div className="flex-1 w-full h-full pt-3">
              <GasChart selectedSensorId={selectedSensorId} />
            </div>
          </div>

          <div className="h-1/2 bg-gray-800 rounded-lg p-4 border border-gray-700 flex flex-col">
            <h2 className="font-bold border-b border-gray-700 pb-2 text-sm text-gray-200 flex justify-between items-center">
              <span>■ PTZ 카메라 영상 (CAM-PTZ-01)</span>
              <span className="text-xs bg-red-600 text-white px-2 py-0.5 rounded-full animate-pulse">🔴 LIVE</span>
            </h2>
            <div className="flex-1 w-full h-full pt-2 flex flex-col justify-center items-center relative overflow-hidden rounded bg-black mt-2 border border-gray-700">
              <video
                autoPlay loop muted playsInline
                style={{ transform: `scale(${zoomLevel})` }}
                className={`w-full h-full object-cover transition-all duration-300 ${isThermal ? "hue-rotate-180 invert brightness-125 contrast-200" : "opacity-80"}`}
                src="https://assets.mixkit.co/videos/preview/mixkit-forest-stream-in-the-sunlight-529-large.mp4"
              />
              <div className="absolute top-2 left-2 bg-black/60 text-white text-[10px] px-2 py-1 rounded backdrop-blur">
                FOV: 45° | Tilt: -15° | Mode: {isThermal ? "🔥 IR Thermal" : "📷 Visible"} | Zoom: {zoomLevel}x
              </div>
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