"use client";

import { useEffect, useRef, useState, useImperativeHandle, forwardRef } from "react";

// 💡 [가상 센서 데이터 및 백엔드 노드 매핑]
export const MOCK_SENSORS = [
  {
    id: "NODE_WUI_0102",
    name: "🔥 백엔드 수집 노드 (NODE_WUI_0102)",
    lat: 37.8853,
    lng: 127.7669,
    co: "대기 중...",
    status: "NORMAL",
    color: "GREEN",
  },
  {
    id: "GAS-Node-01",
    name: "🔥 WUI A구역 가스 센서 1호",
    lat: 37.8910,
    lng: 127.7720,
    co: "12 ppm (정상)",
    status: "NORMAL",
    color: "GREEN",
  },
  {
    id: "CAM-PTZ-01",
    name: "📷 메인 산악 PTZ 감시 카메라",
    lat: 37.8800,
    lng: 127.7600,
    co: "정상 작동 중",
    status: "NORMAL",
    color: "BLUE",
  },
];

const CesiumMap = forwardRef((/** @type {{ enableForecast?: boolean }} */ props, ref) => {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [loaded, setLoaded] = useState(false);
  const [selectedSensor, setSelectedSensor] = useState(null);
  const [forecastMetadata, setForecastMetadata] = useState(null);

  // 부모 컴포넌트(page.tsx)에서 실시간 백엔드 데이터에 맞춰 시점 이동 및 마커 바인딩
  useImperativeHandle(ref, () => ({
    flyToSensor: (sensorId) => {
      const sensor = MOCK_SENSORS.find((s) => s.id === sensorId) || MOCK_SENSORS[0];
      if (sensor && viewerRef.current && window.Cesium) {
        const Cesium = window.Cesium;
        setSelectedSensor(sensor);
        viewerRef.current.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(sensor.lng, sensor.lat, 3000),
          duration: 1.5,
        });
      }
    },
    updateAndFlyToSensor: (sensorId, gasData) => {
      const sensor = MOCK_SENSORS.find((s) => s.id === sensorId) || MOCK_SENSORS[0];
      if (sensor) {
        sensor.co = `CO: ${gasData?.CO ?? 85.5} ppm (위험)`;
        sensor.status = "DANGER";
        sensor.color = "RED";
        setSelectedSensor({ ...sensor });

        if (viewerRef.current && window.Cesium) {
          const Cesium = window.Cesium;
          const entity = viewerRef.current.entities.getById(sensor.id);
          if (entity && entity.point) {
            entity.point.color = Cesium.Color.RED;
          }
          viewerRef.current.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(sensor.lng, sensor.lat, 2500),
            duration: 1.2,
          });
        }
      }
    },
  }));

  useEffect(() => {
    // 1. Cesium CSS 로드
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://cesium.com/downloads/cesiumjs/releases/1.119/Build/Cesium/Widgets/widgets.css";
    document.head.appendChild(link);

    // 2. Cesium JS 스크립트 로드
    const script = document.createElement("script");
    script.src = "https://cesium.com/downloads/cesiumjs/releases/1.119/Build/Cesium/Cesium.js";
    script.async = true;
    script.onload = () => {
      setLoaded(true);
    };
    document.head.appendChild(script);
  }, []);

  useEffect(() => {
    if (loaded && containerRef.current && window.Cesium) {
      const Cesium = window.Cesium;

      // Viewer 생성
      const viewer = new Cesium.Viewer(containerRef.current, {
        baseLayer: new Cesium.ImageryLayer(
          new Cesium.OpenStreetMapImageryProvider({
            url: "https://tile.openstreetmap.org/",
          })
        ),
        timeline: false,
        animation: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
      });

      viewerRef.current = viewer;

      if (props.enableForecast) {
        fetch('/api/edgefire/forecast', {cache: 'no-store'})
          .then(response => { if (!response.ok) throw new Error('Forecast unavailable'); return response.json(); })
          .then(async data => {
            if (viewer.isDestroyed()) return;
            const layer = await Cesium.GeoJsonDataSource.load(data, {
              clampToGround: true, stroke: Cesium.Color.ORANGE,
              fill: Cesium.Color.ORANGE.withAlpha(0.15), strokeWidth: 1,
            });
            if (viewer.isDestroyed()) return;
            viewer.dataSources.add(layer);
            setForecastMetadata(data.metadata);
          }).catch(() => {});
      }

      // 카메라 기본 위치 설정
      viewer.camera.setView({
        destination: Cesium.Rectangle.fromDegrees(125.8, 36.8, 129.6, 38.7),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch: Cesium.Math.toRadians(-90),
          roll: 0,
        },
      });

      // 📍 센서 마커 추가
      MOCK_SENSORS.forEach((sensor) => {
        let pinColor = Cesium.Color.GREEN;
        if (sensor.status === "WARNING") pinColor = Cesium.Color.ORANGE;
        if (sensor.status === "DANGER") pinColor = Cesium.Color.RED;
        if (sensor.color === "BLUE") pinColor = Cesium.Color.DODGERBLUE;

        viewer.entities.add({
          id: sensor.id,
          name: sensor.name,
          position: Cesium.Cartesian3.fromDegrees(sensor.lng, sensor.lat, 100),
          point: {
            pixelSize: 16,
            color: pinColor,
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 3,
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          },
          label: {
            text: sensor.id,
            font: "13px sans-serif",
            fillColor: Cesium.Color.WHITE,
            showBackground: true,
            backgroundColor: new Cesium.Color(0, 0, 0, 0.7),
            pixelOffset: new Cesium.Cartesian2(0, -25),
          },
        });
      });

      // 🖱️ 클릭 이벤트
      const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handler.setInputAction((click) => {
        const pickedObject = viewer.scene.pick(click.position);
        if (Cesium.defined(pickedObject) && pickedObject.id) {
          const sensorId = pickedObject.id.id;
          const foundSensor = MOCK_SENSORS.find((s) => s.id === sensorId);
          if (foundSensor) {
            setSelectedSensor(foundSensor);
          }
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      return () => {
        handler.destroy();
        if (viewer && !viewer.isDestroyed()) {
          viewer.destroy();
        }
      };
    }
  }, [loaded, props.enableForecast]);

  return (
    <div className="w-full h-full relative">
      {forecastMetadata && <div className="absolute top-2 left-2 z-10 bg-black/80 text-white text-[10px] p-2 rounded max-w-[90%]">
        확산 추정 · 입력 조건 기준 · 미검증<br />
        {forecastMetadata.input_time} · ERA5 {forecastMetadata.wind_ms}m/s · 풍향 {forecastMetadata.wind_from_deg}°<br />
        수도권·강원도 · 춘천 가정 발화점 · 평지·균일 연료 · 10/20/30분
      </div>}
      {!loaded && (
        <div className="flex items-center justify-center h-full text-gray-400">
          🌍 3D GIS 관제 지도 및 센서 데이터 로딩 중...
        </div>
      )}

      <div ref={containerRef} className="w-full h-full rounded-lg overflow-hidden" />

      {/* 📌 센서 상세 정보 팝업창 */}
      {selectedSensor && (
        <div className="absolute top-4 right-4 bg-gray-900/90 border border-gray-700 text-white p-4 rounded-lg shadow-xl z-10 w-72 backdrop-blur-md">
          <div className="flex justify-between items-center border-b border-gray-700 pb-2 mb-3">
            <h3 className="font-bold text-sm text-yellow-400">{selectedSensor.name}</h3>
            <button
              onClick={() => setSelectedSensor(null)}
              className="text-gray-400 hover:text-white text-xs px-1"
            >
              ✕ 닫기
            </button>
          </div>
          <div className="space-y-2 text-xs text-gray-300">
            <p><span className="text-gray-500">장비 ID:</span> {selectedSensor.id}</p>
            <p><span className="text-gray-500">위도/경도:</span> {selectedSensor.lat}, {selectedSensor.lng}</p>
            <p>
              <span className="text-gray-500">가스/상태:</span>{" "}
              <span className={selectedSensor.status === "DANGER" ? "text-red-400 font-bold animate-pulse" : "text-green-400 font-bold"}>
                {selectedSensor.co}
              </span>
            </p>
          </div>
        </div>
      )}
    </div>
  );
});

CesiumMap.displayName = "CesiumMap";
export default CesiumMap;
