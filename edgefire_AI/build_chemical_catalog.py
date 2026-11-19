"""실제 화학물질 JSON에서 CID·물성·출처를 로컬 카탈로그로 추출합니다."""
from pathlib import Path
import sys,json,zipfile
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'Downloads'
folder=next(root.glob('57.*'));catalog={};count=0
for z in sorted(folder.rglob('*.zip')):
 if not z.name.startswith(('TL_','VL_')):continue
 with zipfile.ZipFile(z) as f:
  for n in f.namelist():
   if not n.endswith('.json'):continue
   d=json.loads(f.read(n));p=d.get('common_properties',{});cid=str(p.get('cid') or '')
   if not cid:continue
   count+=1
   record=catalog.setdefault(cid,{'cid':cid,'name':p.get('iupac_name'),'cas_number':p.get('cas_number'),'smiles':p.get('smiles'),'data_origin':'AI_Hub_chemical_dataset','properties':{},'operational_use':False})
   for prop,section,key,field in [('vapor_pressure','vapor_pressure_properties','vapor_pressure','vp'),('heat_of_combustion','heat_of_combustion_properties','heat_combustion','heat_comb'),('flash_point','flash_point_properties','flash_point','fp')]:
    values=record['properties'].setdefault(prop,[])
    for item in d.get(section,{}).get(key,[]):
     v=item.get(field)
     if isinstance(v,(int,float)):
      entry={'value':v,'temperature_celsius':item.get('temp_celsius'),'datasource':item.get('datasource'),'units_verified':False}
      if entry not in values:values.append(entry)
Path(__file__).with_name('chemical_catalog.json').write_text(json.dumps({'records':catalog,'label_records_read':count,'unique_cids':len(catalog),'notes':'원시 물성 조회 자료입니다. 단위·측정법 미검증. 가스 센서 학습자료나 위험 판정 모델이 아닙니다.'},ensure_ascii=False),encoding='utf8')
print('Chemical label records:',count,'unique CIDs:',len(catalog))
