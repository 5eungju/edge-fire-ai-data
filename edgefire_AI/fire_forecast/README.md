# 발생·확산 연구 모듈

기존 YOLO 학습과 별도인 CPU 1스레드 작업이다. 결과는 C드라이브에 저장한다. 지도 범위는 수도권·강원도이며 서울·수원·인천·춘천·원주·강릉 6개 지점의 시간자료를 확보했다. 현재 확산 격자는 춘천 한 지점의 가정 발화점에만 생성한다. 전 지역의 실제 발화/확산을 예측한 것이 아니다.

기상 자료 재수집은 edgefire_AI 폴더에서 `py -m fire_forecast.fetch_weather --root C:/Users/tmdwn/Documents/Codex/2026-11-19/new-chat/outputs/fire_forecast_202512`로 실행한다. requests가 필요하다.

```powershell
py edgefire_AI/fire_forecast/run.py --root C:/Users/tmdwn/Documents/Codex/2026-11-19/new-chat/outputs/fire_forecast_202512 --surrogate-samples 120
```

## 실행된 것과 실행되지 않은 것

- 2025-12-01~10, 기존 지도 중심 37.8853/127.7669의 ERA5 시간자료 240행 확보. 지역은 사용자 확인 전 잠정 선택이다. 재분석이며 현장 관측이 아니다.
- 12월 1일 12시 자료로 20m 격자, 10/20/30분 도달 범위 계산. 발화점은 지도 중심 가정이고 실제 발생 사건이 아니다.
- 휴리스틱 8방향 도달시간 계산이다. FARSITE 또는 검증된 Rothermel 구현을 주장하지 않는다. 기본 확산속도 1m/min, 평지, 균일 연료 가정이며 비화/진화/수관화/적설을 계산하지 않는다. 기본 계수는 현장 보정되지 않았다.
- 120개 임의 입력 조합으로 계산기를 재현하는 HistGradientBoostingRegressor 보조 모델 학습. 정답은 시뮬레이터 출력이다. 오차는 계산기 재현 오차일 뿐 실제 산불 오차가 아니다.
- 실제 발생/미발생 라벨이 없으면 발생 모델은 학습하지 않고 WAITING_FOR_REAL_LABELS 기록.
- 실제 시간별 경계가 없으면 확산 지도 학습은 시작하지 않는다. 이미지 분할 라벨은 지리적 화재 경계를 대신하지 않는다.
- 화면 표기는 '확산 추정 · 입력 조건 기준 · 미검증'이다. 실제 대응 판단에 사용하지 않는다.

## 발생 학습 입력

`<root>/inputs/occurrence.csv`의 열:

`issued_at,region_id,label,temperature_c,humidity_pct,wind_ms,rain_previous_7d_mm,source_type`

label은 발행시점 이후 24시간 내 실제 산불 발생(1)/미발생(0)이다. source_type은 observed. 미발생 라벨은 해당 지역·기간의 사건 기록 포괄성이 확인되어야 한다. 기상 특징은 발행시점에 이용 가능한 자료만 사용한다. 피해면적·진화시간·미래 실제 관측값을 입력에 넣지 않는다. 지역/시간 중복을 거부하고 날짜 기준 80/20 분할 및 2일 간격을 적용한다. 최소 30일은 개발용 실행 조건일 뿐 데이터 충분성 기준이 아니다. 실제 배포에는 여러 해, 지역 외부 검증, 확률 보정 및 시간별 유병률 평가가 별도로 필요하다.

## 실제 확산 경계 감사

`<root>/inputs/perimeters.geojson`에 Polygon/MultiPolygon을 저장한다. properties는 `event_id,observed_at,source_type`이고 observed_at은 시간대가 포함된 실제 경계 관측시각, source_type은 observed이다. 파일 편집시각은 관측시각이 아니다.

동일 사건의 서로 다른 시각 경계 최소 2개가 있어야 변화량 한 쌍을 만든다. 30분 목표에는 해당 시간 간격의 관측이 필요하며 하루 단위 최종 경계를 임의 보간해 정답으로 만들지 않는다. 동일 좌표계, 유효 도형, 경계 위치 오차, 기상·지형·연료 대응 여부를 확인한 후 사건 단위 학습/검증/시험을 나눈다. 여러 독립 사건과 계절에서 학습곡선 및 시험 오차가 안정되어야 충분성을 판단할 수 있다. 일정 시간이 지나면 자동 충족되는 조건이 아니다.

현재 감사는 기본 형식·시각 간격만 점검하며 도형 타당성/정확도/교란요인 검증을 통과했다고 판단하지 않는다. ready_for_spread_training은 보수적으로 false로 유지한다.

## 출처

- https://open-meteo.com/en/docs/historical-weather-api (ERA5, 0.25도 재분석)
- https://www.data.go.kr/data/15121380/fileData.do (국내 발생 통계; 2025년 자료 포함 여부 별도 확인)
- https://iftdss.firenet.gov/firenetHelp/help/pageHelp/content/10-ftem/datatechnical/wildfiredataabout.htm (WFIGS 공개 경계 및 갱신 제약; 미국 자료가 국내 사건을 대체하지 않음)

기상 자료 재배포 시 Open-Meteo/ERA5 출처·이용조건을 보존한다. 비밀키·개인 파일·학습 체크포인트·원시 데이터는 Git에 추가하지 않는다.
