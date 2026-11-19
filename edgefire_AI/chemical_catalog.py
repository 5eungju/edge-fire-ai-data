from pathlib import Path
import os,json
from fastapi import HTTPException
_catalog=None
def lookup(cid):
 global _catalog
 path=Path(os.getenv('CHEMICAL_CATALOG_PATH',str(Path(__file__).with_name('chemical_catalog.json'))))
 if _catalog is None:
  if not path.is_file():raise HTTPException(503,detail='화학물질 카탈로그가 없습니다. build_chemical_catalog.py를 실행하세요.')
  _catalog=json.loads(path.read_text(encoding='utf8'))
 record=_catalog['records'].get(cid)
 if record is None:raise HTTPException(404,detail='카탈로그에 해당 CID가 없습니다.')
 return {**record,'risk_level':None,'notes':_catalog['notes']}
