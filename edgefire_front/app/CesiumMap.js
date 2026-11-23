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

const CesiumMap = forwardRef((/** @type {{ enableForecast?: boolean, onRegionChange?: (id: string) => void }} */ props, ref) => {
  const regionChangeRef = useRef(props.onRegionChange);
  regionChangeRef.current = props.onRegionChange;
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [loaded, setLoaded] = useState(false);
  const [selectedSensor, setSelectedSensor] = useState(null);
  const [forecastMetadata, setForecastMetadata] = useState(null);
  const [forecastRegions, setForecastRegions] = useState([]);
  const [forecastTimes, setForecastTimes] = useState([]);
  const [regionId, setRegionId] = useState("seoul");
  const [inputTime, setInputTime] = useState("2025-12-01T12:00");
  const [forecastBusy, setForecastBusy] = useState(false);
  const [forecastError, setForecastError] = useState("");
  const [pickingPoint, setPickingPoint] = useState(false);
  const pointRef = useRef(null);
  const regionRef = useRef("seoul");
  const timeRef = useRef("2025-12-01T12:00");
  const pickingRef = useRef(false);
  const sequenceRef = useRef(0);
  const requestRef = useRef(null);
  const layerRef = useRef(null);
  const calculateRef = useRef(null);

  async function runForecast(payload) {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;
    const sequence = ++sequenceRef.current;
    requestRef.current?.abort();
    const controller = new AbortController(); requestRef.current = controller;
    setForecastBusy(true); setForecastError("");
    try {
      const response = await fetch('/api/edgefire/forecast', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),signal:controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '확산 계산 실패');
      if (sequence !== sequenceRef.current || viewer.isDestroyed()) return;
      const Cesium = window.Cesium;
      // Large horizon first, smaller horizons on top; only one result set remains.
      const collection = {...data,features:[...data.features].reverse()};
      const layer = await Cesium.GeoJsonDataSource.load(collection, {clampToGround:true,
        stroke:Cesium.Color.ORANGE,fill:Cesium.Color.ORANGE.withAlpha(.22),strokeWidth:1});
      if (sequence !== sequenceRef.current || viewer.isDestroyed()) { if (typeof layer.destroy === "function") layer.destroy(); return; }
      layer.entities.values.forEach(entity => {
        if (entity.polygon) {
          const minutes = entity.properties.minutes.getValue();
          entity.polygon.material = (minutes===10 ? Cesium.Color.RED : minutes===20 ? Cesium.Color.ORANGE : Cesium.Color.YELLOW).withAlpha(.3);
        }
      });
      if (layerRef.current) viewer.dataSources.remove(layerRef.current,true);
      viewer.dataSources.add(layer); layerRef.current = layer;
      viewer.entities.removeById('selected-ignition');
      viewer.entities.add({id:'selected-ignition',name:'선택한 가정 발화점',
        position:Cesium.Cartesian3.fromDegrees(data.metadata.longitude,data.metadata.latitude),
        point:{pixelSize:10,color:Cesium.Color.RED,outlineColor:Cesium.Color.WHITE,outlineWidth:2},
        label:{text:'선택 발화점 · 가정',font:'12px sans-serif',showBackground:true,pixelOffset:new Cesium.Cartesian2(0,-20)}});
      setForecastMetadata(data.metadata);
      viewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(data.metadata.longitude,data.metadata.latitude,1600),
        orientation:{heading:0,pitch:Cesium.Math.toRadians(-90),roll:0},duration:.8});
    } catch (error) {
      if (error.name !== 'AbortError' && sequence === sequenceRef.current) setForecastError(error.message || String(error));
    } finally { if (sequence === sequenceRef.current) setForecastBusy(false); }
  }
  calculateRef.current = runForecast;

  function chooseRegion(id) {
    regionRef.current=id; setRegionId(id); pointRef.current=null;
    regionChangeRef.current?.(id);
    pickingRef.current=false;setPickingPoint(false);setSelectedSensor(null);
    calculateRef.current?.({region:id,input_time:timeRef.current});
  }
  function recalculate() {
    calculateRef.current?.({region:regionRef.current,input_time:timeRef.current,...(pointRef.current || {})});
  }


  // 부모 컴포넌트(page.tsx)에서 실시간 백엔드 데이터에 맞춰 시점 이동 및 마커 바인딩
  useImperativeHandle(ref, () => ({
    flyToSensor: (sensorId) => {
      const sensor = MOCK_SENSORS.find((s) => s.id === sensorId) || MOCK_SENSORS[0];
      if (sensor && viewerRef.current && window.Cesium) {
        const Cesium = window.Cesium;
        setSelectedSensor(sensor);
        if (props.enableForecast) return;
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
        fetch('/api/edgefire/forecast/regions', {cache:'no-store'})
          .then(response => {if (!response.ok) throw new Error('지역 목록 연결 실패');return response.json();})
          .then(data => {
            if (viewer.isDestroyed()) return;
            setForecastRegions(data.regions); setForecastTimes(data.times);
            data.regions.forEach(region => viewer.entities.add({id:'weather-'+region.id,
              name:region.name+' 기상 대표 지점',position:Cesium.Cartesian3.fromDegrees(region.longitude,region.latitude),
              point:{pixelSize:9,color:Cesium.Color.DODGERBLUE,outlineColor:Cesium.Color.WHITE,outlineWidth:1},
              label:{text:region.name,font:'12px sans-serif',showBackground:true,pixelOffset:new Cesium.Cartesian2(0,-18)}}));
            calculateRef.current?.({region:regionRef.current,input_time:timeRef.current});
          }).catch(error => {if (!viewer.isDestroyed()) setForecastError(error.message);});
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
      (props.enableForecast ? [] : MOCK_SENSORS).forEach((sensor) => {
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
        if (props.enableForecast && pickingRef.current) {
          const ray = viewer.camera.getPickRay(click.position);
          const cartesian = viewer.scene.globe.pick(ray,viewer.scene) || viewer.camera.pickEllipsoid(click.position);
          if (!cartesian) {setForecastError('지도 표면을 선택해 주세요.');return;}
          const position = Cesium.Cartographic.fromCartesian(cartesian);
          const latitude = Cesium.Math.toDegrees(position.latitude), longitude = Cesium.Math.toDegrees(position.longitude);
          if (latitude < 36.8 || latitude > 38.7 || longitude < 125.8 || longitude > 129.6) {
            setForecastError('수도권·강원도 범위 안에서 선택해 주세요.');return;
          }
          pointRef.current={latitude,longitude};regionRef.current='map';setRegionId('map');
          regionChangeRef.current?.('map');
          pickingRef.current=false;setPickingPoint(false);setSelectedSensor(null);
          calculateRef.current?.({region:'map',latitude,longitude,input_time:timeRef.current});return;
        }

        if (Cesium.defined(pickedObject) && pickedObject.id) {
          const sensorId = pickedObject.id.id;
          if (props.enableForecast && typeof sensorId === 'string' && sensorId.startsWith('weather-')) {
            chooseRegion(sensorId.slice(8));return;
          }
          const foundSensor = MOCK_SENSORS.find((s) => s.id === sensorId);
          if (foundSensor) {
            setSelectedSensor(foundSensor);
          }
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      return () => {
        ++sequenceRef.current; requestRef.current?.abort(); layerRef.current=null; viewerRef.current=null;
        handler.destroy();
        if (viewer && !viewer.isDestroyed()) {
          viewer.destroy();
        }
      };
    }
  }, [loaded, props.enableForecast]);

  return (
    <div className="w-full h-full relative">
      {props.enableForecast && <div className="absolute top-2 left-2 z-10 bg-black/85 text-white text-[10px] p-2 rounded max-w-[94%] flex flex-col gap-1">
        <div className="flex flex-wrap gap-1 items-center">
          <label>지역 <select aria-label="계산 지역" value={regionId} onChange={event => chooseRegion(event.target.value)} className="bg-gray-800 rounded p-1">
            {forecastRegions.map(region => <option key={region.id} value={region.id}>{region.name}</option>)}
            {regionId === 'map' && <option value="map">지도 선택 지점</option>}
          </select></label>
          <label>시각 <select aria-label="기상 시각" value={inputTime} onChange={event => {timeRef.current=event.target.value;setInputTime(event.target.value);recalculate();}} className="bg-gray-800 rounded p-1 max-w-[155px]">
            {forecastTimes.map(time => <option key={time} value={time}>{time.replace('T',' ')}</option>)}
          </select></label>
        </div>
        <div className="flex flex-wrap gap-1">
          <button className="bg-blue-700 rounded px-2 py-1" onClick={() => {pickingRef.current=!pickingRef.current;setPickingPoint(pickingRef.current);}}>{pickingPoint ? '지도 클릭 대기 · 취소' : '지도에서 발화점 선택'}</button>
          <button className="bg-gray-700 rounded px-2 py-1" onClick={recalculate}>다시 계산</button>
          <button className="bg-gray-700 rounded px-2 py-1" onClick={() => {const viewer=viewerRef.current;if(viewer && !viewer.isDestroyed()) viewer.camera.setView({destination:window.Cesium.Rectangle.fromDegrees(125.8,36.8,129.6,38.7),orientation:{heading:0,pitch:-Math.PI/2,roll:0},duration:.8});}}>전체 지역 보기</button>
        </div>
        <p role="status">{forecastBusy ? '선택 지점·시각으로 계산 중…' : '확산 추정 · 입력 조건 기준 · 미검증'}</p>
        {forecastError && <p role="alert" className="text-red-300">{forecastError} {forecastMetadata ? '(이전 결과 유지)' : ''}</p>}
        {forecastMetadata && <>
          <p>계산 위치: {forecastMetadata.region_name} {forecastMetadata.latitude.toFixed(5)}, {forecastMetadata.longitude.toFixed(5)}</p>
          <p>{forecastMetadata.input_time.replace('T',' ')} · ERA5 {forecastMetadata.wind_ms}m/s · 풍향 {forecastMetadata.wind_from_deg}° · 습도 {forecastMetadata.humidity_pct}%</p>
          <p>기상 대표 지점: {forecastMetadata.weather_region_name} · 거리 {forecastMetadata.representative_point_distance_km}km</p>
          <p>가정 발화점 · 평지·균일 연료 · 빨강 10 / 주황 20 / 노랑 30분</p>
          <p>파랑 점: 기상 대표 지점 · 사진은 지도와 별도 입력</p>
        </>}
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
