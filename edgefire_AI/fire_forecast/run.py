"""Research grid spread and simulator surrogate; never invent occurrence labels.

Wind direction follows meteorological FROM convention. Geometry uses WGS84.
This heuristic is not FARSITE/Rothermel and is not operationally calibrated.
"""
import argparse
import csv
import heapq
import json
import math
import os
from pathlib import Path

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
import numpy as np


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def arrival(wind_ms, wind_from_deg, humidity, base_m_min=1.0,
            n=101, cell_m=20.0, fuel=None, elevation=None):
    """8-neighbor shortest arrival times on a local north-up grid, minutes."""
    values = [wind_ms, wind_from_deg, humidity, base_m_min, cell_m]
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError('Nonfinite meteorology or grid input')
    if wind_ms < 0 or not 0 <= humidity <= 100 or base_m_min <= 0 or cell_m <= 0:
        raise ValueError('Invalid input range')
    fuel = np.ones((n, n)) if fuel is None else np.asarray(fuel)
    elevation = np.zeros((n, n)) if elevation is None else np.asarray(elevation)
    if fuel.shape != (n, n) or elevation.shape != (n, n):
        raise ValueError('Raster dimensions do not match grid')
    if not np.isfinite(fuel).all() or not np.isfinite(elevation).all() or (fuel < 0).any():
        raise ValueError('Invalid raster values')
    center = n // 2
    if fuel[center, center] <= 0:
        raise ValueError('Ignition cell must be burnable')
    times = np.full((n, n), np.inf)
    times[center, center] = 0
    queue = [(0.0, center, center)]
    # Rows increase southwards. Wind TO is FROM + 180 degrees.
    wind_to = math.radians((wind_from_deg + 180) % 360)
    east, north = math.sin(wind_to), math.cos(wind_to)
    while queue:
        t, y, x = heapq.heappop(queue)
        if t != times[y, x]:
            continue
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if (dx == 0 and dy == 0) or not (0 <= yy < n and 0 <= xx < n):
                    continue
                if fuel[yy, xx] <= 0:
                    continue
                # Prevent corner-cutting across nonburnable raster barriers.
                if dx and dy and (fuel[y, xx] <= 0 or fuel[yy, x] <= 0):
                    continue
                length = math.hypot(dx, dy)
                projection = (east * dx - north * dy) / length
                grade = (elevation[yy, xx] - elevation[y, x]) / (cell_m * length)
                rate = base_m_min * max(.1, 1 - .008 * humidity)
                rate *= math.exp(np.clip(.12 * wind_ms * projection + 2 * grade, -2, 2))
                rate *= float((fuel[y, x] + fuel[yy, xx]) / 2)
                candidate = t + cell_m * length / max(.01, rate)
                if candidate < times[yy, xx]:
                    times[yy, xx] = candidate
                    heapq.heappush(queue, (candidate, yy, xx))
    return times


def summary(times, minute, cell):
    cells = np.argwhere(times <= minute)
    offset = cells - np.array(times.shape) // 2
    radius = np.hypot(offset[:, 0], offset[:, 1]).max() * cell
    return dict(area_m2=len(cells)*cell*cell, max_distance_m=float(radius),
                domain_clipped=bool(np.any((cells == 0) | (cells == times.shape[0]-1))))


def feature_collection(times, lat, lon, cell):
    features = []
    n = times.shape[0]
    def coordinate(x, y):
        return [lon + x / (111320 * math.cos(math.radians(lat))), lat + y / 111320]
    for minute in (10, 20, 30):
        # Exact occupied grid cells: this does not imply measured fire perimeters.
        polygons = []
        for y, x in np.argwhere(times <= minute):
            west, north = (x-n//2-.5)*cell, (n//2-y+.5)*cell
            ring = [coordinate(west,north), coordinate(west+cell,north),
                    coordinate(west+cell,north-cell), coordinate(west,north-cell),
                    coordinate(west,north)]
            polygons.append([ring])
        features.append(dict(type='Feature', properties=dict(minutes=minute,
            **summary(times,minute,cell)), geometry=dict(type='MultiPolygon',coordinates=polygons)))
    return dict(type='FeatureCollection', features=features)


def audit(root):
    source = root/'inputs/perimeters.geojson'
    groups, rejected = {}, 0
    if source.exists():
        from datetime import datetime
        for feature in json.loads(source.read_text(encoding='utf-8'))['features']:
            p = feature.get('properties', {})
            try:
                timestamp = datetime.fromisoformat(p['observed_at'].replace('Z','+00:00'))
                if timestamp.tzinfo is None or p.get('source_type') != 'observed':
                    raise ValueError('Observed timestamp with timezone required')
                if feature['geometry']['type'] not in ('Polygon','MultiPolygon'):
                    raise ValueError('Need actual boundary geometry')
                groups.setdefault(p['event_id'], set()).add(timestamp)
            except (KeyError, ValueError, TypeError):
                rejected += 1
    pairs = 0
    for timestamps in groups.values():
        ordered = sorted(timestamps)
        pairs += sum(0 < (b-a).total_seconds() <= 1800 for a,b in zip(ordered,ordered[1:]))
    # A minimum audit condition, not a claim of statistical sufficiency.
    report = dict(observed_events=len(groups), within_30min_pairs=pairs,
        rejected_records=rejected, ready_for_spread_training=False,
        reason='Need valid aligned boundaries, meteorology, terrain/fuel and independent event evaluation',
        criteria=['Same incident has >=2 distinct observed boundary timestamps',
                  '30-minute targets need boundaries at appropriate <=30-minute intervals',
                  'Valid CRS/geometries; pair with contemporaneous weather and fuel/terrain',
                  'Split by incident and evaluate held-out seasons/regions',
                  'Sufficiency decided by learning curve and held-out errors, not file size'])
    occurrence = root/'inputs/occurrence.csv'
    report['occurrence_table_present'] = occurrence.exists()
    write(root/'data_readiness.json',report)
    return report


def train_occurrence(root):
    """Use real assembled labels only; input features must be known at issuance."""
    source = root/'inputs/occurrence.csv'
    required = ['issued_at','region_id','label','temperature_c','humidity_pct',
                'wind_ms','rain_previous_7d_mm','source_type']
    if not source.exists():
        write(root/'occurrence_training_status.json',dict(status='WAITING_FOR_REAL_LABELS',
            trained=False,required_columns=required,target='fire occurrence in next 24 hours',
            reason='Weather alone cannot provide fire/no-fire labels; no synthetic labels used'))
        return
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, brier_score_loss
    import joblib
    rows = list(csv.DictReader(source.open(encoding='utf-8-sig')))
    if not rows or any(set(required)-row.keys() for row in rows):
        raise ValueError('Occurrence columns missing')
    if any(r['source_type'] != 'observed' for r in rows):
        raise ValueError('Occurrence labels must reference real incident records')
    rows.sort(key=lambda r:r['issued_at'])
    if len({(r['issued_at'],r['region_id']) for r in rows}) != len(rows):
        raise ValueError('Duplicate region-time labels')
    dates = sorted({r['issued_at'][:10] for r in rows})
    if len(dates) < 30:
        raise ValueError('Need multiple dates for temporal evaluation; at least 30 for this development gate')
    cutoff = dates[int(.8*len(dates))]
    # A two-day gap avoids overlapping next-24h labels across split.
    from datetime import date, timedelta
    train_end = (date.fromisoformat(cutoff)-timedelta(days=2)).isoformat()
    train = [r for r in rows if r['issued_at'][:10] < train_end]
    test = [r for r in rows if r['issued_at'][:10] >= cutoff]
    def arrays(batch):
        return np.array([[float(r[k]) for k in required[3:7]] for r in batch]),np.array([int(r['label']) for r in batch])
    x,y=arrays(train); xt,yt=arrays(test)
    if set(y) != {0,1} or set(yt) != {0,1}:
        raise ValueError('Both temporal splits require real positive and negative labels')
    model=HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,random_state=42)
    model.fit(x,y)
    scores=model.predict_proba(xt)[:,1]
    joblib.dump(dict(model=model,features=required[3:7],status='research_unvalidated'),root/'occurrence.joblib')
    write(root/'occurrence_training_status.json',dict(status='TRAINED_RESEARCH_BASELINE',
        trained=True,train_rows=len(y),test_rows=len(yt),average_precision=float(average_precision_score(yt,scores)),
        brier=float(brier_score_loss(yt,scores)),operational_use=False))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--surrogate-samples',type=int,default=120)
    args=parser.parse_args(); root=args.root.resolve(); root.mkdir(parents=True,exist_ok=True)
    if root.drive.upper() != 'C:':
        raise ValueError('This run must save to C:')
    readiness=audit(root); train_occurrence(root)
    weather=json.loads((root/'weather_era5_20251201_10.json').read_text(encoding='utf-8'))
    hourly=weather['hourly']; index=hourly['time'].index('2025-12-01T12:00')
    wind=float(hourly['wind_speed_10m'][index]); direction=float(hourly['wind_direction_10m'][index]); humidity=float(hourly['relative_humidity_2m'][index])
    times=arrival(wind,direction,humidity)
    np.save(root/'arrival_minutes.npy',times)
    geo=feature_collection(times,37.8853,127.7669,20)
    geo['metadata']=dict(display_label='확산 추정 · 입력 조건 기준',operational_use=False,
        calibration='unvalidated_heuristic',wind_source='ERA5 reanalysis, not station observation',
        input_time=hourly['time'][index],wind_ms=wind,wind_from_deg=direction,humidity_pct=humidity,
        ignition='assumed map center, not a detected fire',terrain='flat assumption',fuel='uniform assumption',
        base_rate_m_min=1.0,cell_m=20,notice='No measured fire boundary or calibrated spread rate; not an actual incident forecast')
    write(root/'spread_estimate.geojson',geo)
    # Learn the numerical simulator only. Held-out combinations do NOT validate reality.
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error
    import joblib
    rng=np.random.default_rng(42); x=[]; y=[]
    for _ in range(args.surrogate_samples):
        speed=float(rng.uniform(0,12)); heading=float(rng.uniform(0,360)); rh=float(rng.uniform(15,95)); base=float(rng.uniform(.5,4))
        values=arrival(speed,heading,rh,base,n=51)
        x.append([speed,rh,base]); y.append(summary(values,30,20)['max_distance_m'])
    x=np.array(x);y=np.array(y);split=int(len(y)*.8)
    model=HistGradientBoostingRegressor(max_iter=80,max_leaf_nodes=7,min_samples_leaf=8,random_state=42)
    model.fit(x[:split],y[:split]);score=mean_absolute_error(y[split:],model.predict(x[split:]))
    joblib.dump(dict(model=model,features=['wind_ms','humidity_pct','base_rate_m_min'],
        target='simulated_30min_max_distance_m',operational_use=False),root/'simulator_surrogate.joblib')
    write(root/'surrogate_training_report.json',dict(status='COMPLETED',samples=len(y),train=split,test=len(y)-split,
        labels='heuristic simulator outputs, not observed fire',mae_m=float(score),
        scope='uniform flat grid radial extent only; wind direction omitted because target is rotation invariant',
        real_world_accuracy=None,operational_use=False))
    print(json.dumps(dict(root=str(root),surrogate_samples=len(y),simulator_mae_m=float(score),
        observed_boundary_events=readiness['observed_events']),ensure_ascii=False))


if __name__=='__main__':
    main()
