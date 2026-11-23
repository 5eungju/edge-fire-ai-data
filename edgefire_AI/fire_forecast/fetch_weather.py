"""Download small, attributed ERA5 inputs for the capital area and Gangwon."""
import argparse
import json
from pathlib import Path

import requests
from fire_forecast.run import write

from fire_forecast.catalog import REGIONS



def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    if root.drive.upper() != 'C:':raise ValueError('Use C: storage')
    for name,(lat,lon) in REGIONS.items():
        filename='weather_era5_20251201_10.json' if name=='chuncheon' else f'weather_{name}_20251201_10.json'
        if (root/filename).exists() and not args.refresh:
            existing=json.loads((root/filename).read_text(encoding='utf-8'))
            if len(existing.get('hourly',{}).get('time',[]))==240:
                print(name,'retained',flush=True);continue
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
        print(name,len(data['hourly']['time']),flush=True)


if __name__=='__main__':main()
