"""Download small, attributed ERA5 inputs for the capital area and Gangwon."""
import argparse
from pathlib import Path

import requests
from fire_forecast.run import write

REGIONS = {
    'chuncheon': (37.8853,127.7669), 'seoul': (37.5665,126.978),
    'suwon': (37.2636,127.0286), 'incheon': (37.4563,126.7052),
    'wonju': (37.3422,127.9202), 'gangneung': (37.7519,128.8761),
}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    if root.drive.upper() != 'C:':raise ValueError('Use C: storage')
    for name,(lat,lon) in REGIONS.items():
        params=dict(latitude=lat,longitude=lon,start_date='2025-12-01',end_date='2025-12-10',
            hourly='temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m',
            wind_speed_unit='ms',timezone='Asia/Seoul',models='era5')
        response=requests.get('https://archive-api.open-meteo.com/v1/archive',params=params,timeout=45)
        response.raise_for_status();data=response.json()
        if len(data['hourly']['time']) != 240:raise ValueError('Incomplete hourly weather')
        if any(v is None for key in params['hourly'].split(',') for v in data['hourly'][key]):
            raise ValueError('Missing meteorological values')
        data['_provenance']=dict(source='Open-Meteo ERA5 reanalysis',source_url=response.url,
            observation=False,region=name,requested_latitude=lat,requested_longitude=lon,
            attribution='Open-Meteo and Copernicus Climate Change Service ERA5')
        filename='weather_era5_20251201_10.json' if name=='chuncheon' else f'weather_{name}_20251201_10.json'
        write(root/filename,data)
        print(name,len(data['hourly']['time']))


if __name__=='__main__':main()
