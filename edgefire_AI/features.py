"""관측 가능한 환경 변수만 사용합니다. 최종 피해·종료시각은 제외합니다."""
import math
FEATURES=['temperature','humidity_percent','wind_speed','rainfall','past_rainfall_7days','elevation','slope','wind_sin','wind_cos','aspect_sin','aspect_cos']
LABELS=['매우 낮음','낮음','보통','높음','매우 높음']
def normalize_label(text):
 t=text.replace(' ','').replace('.','')
 if t in ['안전','매우낮음','양호']:return 0
 if t=='낮음':return 1
 if t in ['보통','중간']:return 2
 if t in ['위험','높음','중간에서높음','중간에서높은위험','중간에서높은수준','중간이상']:return 3
 if any(x in t for x in ['매우높','매우위험','극도','극대']):return 4
 return None
def vector(d):
 def n(k):
  v=d.get(k)
  return float(v) if isinstance(v,(int,float)) and math.isfinite(v) else float('nan')
 def trig(k,f):
  v=n(k)
  return f(math.radians(v)) if math.isfinite(v) else float('nan')
 slope=n('slope')
 if not 0<=slope<=90:slope=float('nan')
 return [n(k) for k in FEATURES[:6]]+[slope,trig('wind_direction',math.sin),trig('wind_direction',math.cos),trig('slope_aspect',math.sin),trig('slope_aspect',math.cos)]
