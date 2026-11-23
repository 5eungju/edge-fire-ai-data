"""Offline, attributed spread calculations at selectable capital/Gangwon points."""
import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from fire_forecast.catalog import REGIONS, NAMES
from fire_forecast.run import arrival, feature_collection




def weather_path(root,region):
    return Path(root)/('weather_era5_20251201_10.json' if region=='chuncheon' else f'weather_{region}_20251201_10.json')


def regions(root):
    points=[];common_times=None
    for key,(lat,lon) in REGIONS.items():
        path=weather_path(root,key)
        if not path.exists():continue
        weather=json.loads(path.read_text(encoding='utf-8'))
        times=set(weather['hourly']['time'])
        common_times=times if common_times is None else common_times & times
        points.append(dict(id=key,name=NAMES[key],latitude=lat,longitude=lon,
            weather_grid_latitude=weather['latitude'],weather_grid_longitude=weather['longitude']))
    return dict(regions=points,times=sorted(common_times or []),bounds=[125.8,36.8,129.6,38.7],
        weather_kind='ERA5 reanalysis, representative nearby point; not station observation',
        image_location_linked=False)


def distance_km(lat,lon,lat2,lon2):
    a,b=map(math.radians,[lat,lat2]);delta_lat=b-a;delta_lon=math.radians(lon2-lon)
    h=math.sin(delta_lat/2)**2+math.cos(a)*math.cos(b)*math.sin(delta_lon/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(h)))


def validate(payload):
    if not isinstance(payload,dict) or set(payload)-{'region','latitude','longitude','input_time'}:
        raise ValueError('지역·좌표·시각만 입력해 주세요.')
    region=payload.get('region','seoul')
    if region not in REGIONS and region!='map':raise ValueError('지원하지 않는 지역입니다.')
    custom='latitude' in payload or 'longitude' in payload
    if custom:
        lat,lon=payload.get('latitude'),payload.get('longitude')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [lat,lon]):
            raise ValueError('위도와 경도를 함께 입력해 주세요.')
    elif region=='map':raise ValueError('지도 선택 좌표가 필요합니다.')
    else:lat,lon=REGIONS[region]
    if not (36.8<=lat<=38.7 and 125.8<=lon<=129.6):
        raise ValueError('수도권·강원도 지도 범위 안에서 선택해 주세요.')
    timestamp=payload.get('input_time','2025-12-01T12:00')
    if not isinstance(timestamp,str) or len(timestamp)>20:raise ValueError('지원되는 시각을 선택해 주세요.')
    return region,float(lat),float(lon),timestamp


def calculate(root,payload):
    root=Path(root).resolve();region,lat,lon,timestamp=validate(payload)
    available=regions(root)
    if timestamp not in available['times']:raise ValueError('확보된 기상 자료에 없는 시각입니다.')
    nearest=min(available['regions'],key=lambda r:distance_km(lat,lon,r['weather_grid_latitude'],r['weather_grid_longitude']))
    source=weather_path(root,nearest['id']);raw=source.read_bytes();weather=json.loads(raw)
    hourly=weather['hourly'];index=hourly['time'].index(timestamp)
    if weather['hourly_units'].get('wind_speed_10m')!='m/s':raise ValueError('풍속 단위를 확인해야 합니다.')
    wind=hourly['wind_speed_10m'][index];direction=hourly['wind_direction_10m'][index];humidity=hourly['relative_humidity_2m'][index]
    if any(v is None for v in [wind,direction,humidity]):raise ValueError('선택 시각의 기상 자료가 없습니다.')
    fingerprint=hashlib.sha256(json.dumps([4,region,lat,lon,timestamp,hashlib.sha256(raw).hexdigest()]).encode()).hexdigest()
    target=root/'requests'/(fingerprint+'.geojson')
    if target.exists():return json.loads(target.read_text(encoding='utf-8'))
    result=feature_collection(arrival(wind,direction,humidity),lat,lon,20)
    result['metadata']=dict(request_id=fingerprint,region=region,region_name=NAMES.get(region,'지도 선택'),
        latitude=lat,longitude=lon,input_time=timestamp,wind_ms=wind,wind_from_deg=direction,humidity_pct=humidity,
        weather_region=nearest['id'],weather_region_name=nearest['name'],
        weather_latitude=weather['latitude'],weather_longitude=weather['longitude'],
        representative_point_distance_km=round(distance_km(lat,lon,weather['latitude'],weather['longitude']),2),
        weather_source='ERA5 reanalysis, nearest available representative point',weather_sha256=hashlib.sha256(raw).hexdigest(),
        display_label='확산 추정 · 입력 조건 기준 · 미검증',operational_use=False,
        ignition='user-selected assumed ignition; not an observed fire',terrain='flat assumption',fuel='uniform assumption',
        cell_m=20,base_rate_m_min=1,calibration='unvalidated_heuristic',image_location_linked=False,
        notice='주변 대표 지점의 과거 재분석 자료입니다. 실제 지형·연료·현재 화재·사진 위치와 연결되지 않은 연구 계산입니다.')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    os.replace(temp,target)
    return result
