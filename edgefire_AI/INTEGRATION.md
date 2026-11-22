현재 개인 스토리지 워커 연동은 ../integration/STORAGE_WORKER.md를 따릅니다. 아래 AI HTTP 계약은 이전 경로 참고 자료입니다.

개인 복사본 실행은 ../integration/README.md를 우선 확인하세요. 아래는 기존 AI 계약과 팀 연동 참고 자료입니다.

# 백엔드·프론트 담당자 연동 안내

검토 기준: 공유 저장소 main `f97b78d10796b24ed80140520ca0d85e5bfa5af5`.
이 변경은 `edgefire_AI/`에만 적용됩니다. 아래 백엔드 호출과 화면 표시 연결은 각 담당자가 추후 적용할 작업입니다.

## 현재 구조

백엔드는 `POST /api/v1/telemetry/multimodal`로 CO/H2/VOC 패킷을 받아 `ws://127.0.0.1:8000/api/v1/ws/hazard`로 전달합니다. 프론트는 이 채널에 연결합니다. 기존 백엔드에는 AI 호출과 기상 입력 필드가 없고, 프론트의 위험 배지·일부 경보·94.2% 비전 신뢰도는 시연용 고정값입니다. AI 서버만 실행한다고 기존 화면이 자동으로 AI 결과로 바뀌지는 않습니다.

## 권장 호출 흐름

센서/환경 관측 → 백엔드 → AI `http://127.0.0.1:8001/api/v1/ai/assess` → 백엔드 → 기존 관제 WebSocket → 프론트.

백엔드가 전달할 예시:

```json
{
  "node_id": "NODE_WUI_0102",
  "sequence_no": 1042,
  "timestamp": 1795090000,
  "gas_data": {"CO": 45.2, "H2": 12.1, "VOC": 110.5},
  "camera_azimuth": 185.4,
  "environment": {
    "temperature": 25,
    "humidity_percent": 30,
    "wind_speed": 5,
    "wind_direction": 90,
    "rainfall": 0,
    "past_rainfall_7days": 0,
    "elevation": 300,
    "slope": 15,
    "slope_aspect": 180
  }
}
```

`node_id`는 필수입니다. `environment`를 제공할 경우 온도·습도·풍속이 필수이고 나머지는 선택입니다. `gas_data`와 `camera_azimuth`는 전송된 관측값을 보존하는 필드이며 현재 모델의 추론 입력으로 사용하지 않습니다. 임의의 환경값을 센서 측정값처럼 채우지 마세요. 온도는 섭씨, 습도는 %, 방향은 도 단위입니다. 풍속·강수·고도는 AI 허브 구축 명세와 관측 장치의 단위 일치 여부를 실사용 전 확인해야 합니다.

## 응답 계약

최상위 `node_id`, `sequence_no`, `timestamp`, `gas_data`, `camera_azimuth`를 보존합니다. 제공되지 않은 선택 필드는 생략됩니다. `timestamp`를 생략하면 서버 수신 시각(초)을 사용합니다.

- `event_type`: `hazard_assessment`
- `status`: `RESEARCH_RESULT`, `INSUFFICIENT_INPUT`, `AI_UNAVAILABLE`
- `risk_level`: 1~5 또는 null
- `ai`: 상세 결과·모델 버전·위험 단계·제약

| 상태 | 위험 단계 | 의미 |
|---|---|---|
| RESEARCH_RESULT | 1~5 | 기존 산불 사례의 주석 등급 분류 결과 |
| INSUFFICIENT_INPUT | null | environment 누락. 가스값만으로 위험을 예측하지 않음 |
| AI_UNAVAILABLE | null | 모델 파일 없음 |

`ai.operational_use`는 항상 false입니다. 모델 파일이 있을 때 1=정상, 2=관심, 3=주의, 4=경계, 5=심각이라는 프론트 표시 체계에 맞춘 임시 매핑을 반환합니다. 1단계가 실제 비산불·안전 상태를 검증했다는 의미는 아닙니다. `ai.predicted_annotation_level`에는 원 모델의 주석 등급을 별도로 보존합니다. 분류 점수를 산불 발생 확률이나 화재 확증 신뢰도로 표시하면 안 됩니다.

잘못된 수치·필수 입력 누락·알 수 없는 필드는 422입니다. 기존 `/wildfire/assess`는 모델이 없으면 503을 반환합니다. 연동용 경로에서는 모델 파일 없음도 상태 객체로 돌려주므로 HTTP 200만으로 추론 성공을 판단하지 말고 `status`와 `risk_level`을 함께 확인하세요. 네트워크 단절·서버 종료·시간 초과는 백엔드에서 별도로 AI_UNAVAILABLE로 처리하고 위험 단계를 정상으로 대체하지 마세요.

## 백엔드 담당자 적용 항목

1. 실제로 확보한 `environment` 필드를 수신 스키마에 추가하고 AI로 전달합니다. 기존 백엔드는 이 필드가 없으므로 우선 담당자의 반영이 필요합니다.
2. 비동기 HTTP 클라이언트와 제한시간을 사용해 8001번 AI를 호출합니다.
3. 응답을 데이터로 보존하고 기존 WebSocket으로 전달합니다. 재시도 시 sequence_no·timestamp로 오래된 결과와 중복을 구분합니다.
4. 모델은 CPU 추론이므로 HTTP 호출·모델 실행을 기존 이벤트 루프에서 직접 오래 점유하지 않도록 구성합니다. AI 서버는 FastAPI 동기 엔드포인트를 사용합니다.

## 프론트 담당자 적용 항목

1. `risk_level` 1~5를 `riskLevels.ts` 배지에 연결하고 null은 판단 대기/불가로 표시합니다.
2. `status=RESEARCH_RESULT`와 `operational_use=false`를 연구 시제품 결과로 표시합니다. 이를 실제 경보·자동 신고로 연결하지 않습니다.
3. 노드 ID만으로 띄우는 고정 경보, 고정 CO 값, 94.2% 비전 확증 문구는 실제 데이터 연결 전 시연값으로 명확하게 분리합니다.
4. 센서별 실제 수신값과 시각을 차트에 연결합니다. 현재 gas 차트는 정적 예시입니다.

AI의 입력·출력 예시는 `example_request.json`, `example_response.json`, 기계 판독 명세는 `openapi.json`에 있습니다.


## 합성 가스 확장

선택 필드 `gas_simulation`과 가스 전용/화학 조회 경로는 [SYNTHETIC_DATA.md](SYNTHETIC_DATA.md)를 참고하세요. `gas_data`는 계속 실측값 보존 전용이며 가스 시연 모델로 자동 추론하지 않습니다. 합성 결과를 기존 실측 위험 단계와 합치지 않습니다.
