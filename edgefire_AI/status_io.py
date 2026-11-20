"""모니터링 파일 잠금 때문에 실제 학습이 멈추지 않게 합니다."""
import json
import logging
import os
import time
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def write_status(path, payload, attempts=7, sleeper=time.sleep):
    """완전한 JSON만 교체합니다. 실패하면 이전 기록을 보존하고 False를 반환합니다."""
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf8')
        for attempt in range(attempts):
            try:
                temporary.replace(path)
                return True
            except PermissionError:
                if attempt + 1 < attempts:
                    sleeper(min(.02 * 2**attempt, .2))
        LOGGER.warning('진행상태 파일이 잠겨 있어 이전 기록을 유지합니다. 학습은 계속됩니다: %s', path)
    except OSError as exc:
        LOGGER.warning('진행상태 기록 실패. 학습은 계속됩니다: %s', exc)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return False
