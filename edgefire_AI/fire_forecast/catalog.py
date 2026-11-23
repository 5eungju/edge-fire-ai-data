"""Shared display regions; representative points, not administrative boundaries."""
import json
from pathlib import Path
POINTS = json.loads(Path(__file__).with_name('regions.json').read_text(encoding='utf-8'))
REGIONS = {p['id']:(p['latitude'],p['longitude']) for p in POINTS}
NAMES = {p['id']:p['name'] for p in POINTS}
