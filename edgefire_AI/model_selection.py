"""검증 분할의 고정 점수 기준으로 비교합니다. 시험 성능은 선정에 쓰지 않습니다."""
import math

HAZARDS = {'black_smoke', 'white_gray_smoke', 'flame'}


def score_candidate(result):
    if result.get('split') != 'val':
        raise ValueError('모델 선정에는 검증 분할만 사용할 수 있습니다.')
    operating = result['operating_point']
    if operating['confidence'] != .25:
        raise ValueError('비교 후보는 동일한 점수 기준이 필요합니다.')
    rows = operating['per_class']
    if len(rows) != 6 or not HAZARDS.issubset({r['class_name'] for r in rows}):
        raise ValueError('평가에 필요한 클래스가 없습니다.')
    for row in rows:
        if not all(math.isfinite(row[key]) and 0 <= row[key] <= 1 for key in ['precision', 'recall', 'f1']):
            raise ValueError('유효하지 않은 검증 지표')
    hazard = [r for r in rows if r['class_name'] in HAZARDS]
    hazard_f1 = sum(r['f1'] for r in hazard) / len(hazard)
    macro_f1 = sum(r['f1'] for r in rows) / len(rows)
    return {'selection_score': .8 * hazard_f1 + .2 * macro_f1,
            'hazard_mask_f1': hazard_f1, 'macro_mask_f1': macro_f1,
            'hazard_mask_recall': sum(r['recall'] for r in hazard) / len(hazard)}


def select_candidate(candidates):
    if len(candidates) < 2:
        raise ValueError('비교할 성공 후보가 두 개 이상 필요합니다.')
    if len({c['result']['evaluation_ids_sha256'] for c in candidates}) != 1:
        raise ValueError('동일한 검증 표본을 사용해야 합니다.')
    ranked = [dict(c, **score_candidate(c['result'])) for c in candidates]
    best = max(c['selection_score'] for c in ranked)
    near = [c for c in ranked if best - c['selection_score'] <= .01]
    winner = min(near, key=lambda c: c['result']['benchmark']['p95_ms'])
    return winner, sorted(ranked, key=lambda c: c['selection_score'], reverse=True)
