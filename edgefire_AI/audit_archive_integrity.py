"""원본 이미지 멤버 CRC/크기를 순차 검사합니다. 중간 체크포인트로 재개 가능합니다."""
import argparse
import json
import os
import sqlite3
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock
from prepare_vision_dataset import entry_from_row
from split_zip_reader import ZipReader, MemberIntegrityError
from status_io import write_status


def verify_member(reader, entry):
    """CRC 불일치만 한 번 재확인합니다. 장치 I/O 오류는 손상 판정으로 바꾸지 않습니다."""
    previous_digest = None
    for attempt in range(2):
        try:
            reader.read(entry)
            return None
        except ValueError as exc:
            if not isinstance(exc, MemberIntegrityError) and 'CRC/size mismatch' not in str(exc):
                raise
            digest = getattr(exc, 'compressed_sha256', None)
            if previous_digest and digest and previous_digest != digest:
                raise OSError('같은 위치의 반복 읽기 값이 다릅니다. 파일 손상으로 분류하지 않고 장치 읽기를 확인해야 합니다.')
            previous_digest = digest
            if attempt:
                return str(exc) + (' [compressed SHA256=' + digest + ']' if digest else '')
            reader.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', default='E:/AI_Work/edgefire_vision/vision_index.sqlite')
    parser.add_argument('--output', default='E:/AI_Work/archive_integrity')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect('file:' + args.index + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    original = json.loads(source.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()[0])
    readers = {role: ZipReader(original[role][-1]['path']) for role in ['VS', 'TS']}
    fingerprint = {role: [{'path': str(part), 'bytes': part.stat().st_size, 'mtime_ns': part.stat().st_mtime_ns}
                          for part in reader.parts] for role, reader in readers.items()}
    expected = {role: original[role] for role in readers}
    if fingerprint != expected:
        raise ValueError('원본 파일이 기존 목록과 달라졌습니다. 새 목록을 확인해야 합니다.')
    state = {'pid': os.getpid(), 'started_utc': datetime.now(timezone.utc).isoformat(),
             'original_archives': fingerprint, 'phase': 'initializing', 'scope': 'TS/VS image-member CRC and uncompressed size; not full JPEG pixel decoding',
             'total_images': source.execute("SELECT count(*) FROM members WHERE role IN ('TS','VS')").fetchone()[0]}
    with FileLock(str(output/'audit.lock'), timeout=0):
        audit = sqlite3.connect(output/'progress.sqlite')
        audit.executescript('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);'
                            'CREATE TABLE IF NOT EXISTS checkpoints(role TEXT PRIMARY KEY,state TEXT);'
                            'CREATE TABLE IF NOT EXISTS failures(role TEXT,key TEXT,name TEXT,disk INT,offset INT,error TEXT,PRIMARY KEY(role,key));')
        saved = audit.execute("SELECT value FROM settings WHERE key='fingerprint'").fetchone()
        serialized = json.dumps(fingerprint, sort_keys=True)
        if saved and saved[0] != serialized:
            raise ValueError('원본이 변경돼 이전 검사 기록을 재사용할 수 없습니다. 새 출력 폴더를 사용하세요.')
        audit.execute("INSERT OR REPLACE INTO settings VALUES('fingerprint',?)", (serialized,))
        audit.commit()
        checkpoints = {}
        for role in readers:
            saved = audit.execute('SELECT state FROM checkpoints WHERE role=?', (role,)).fetchone()
            checkpoints[role] = json.loads(saved[0]) if saved else {'disk': -1, 'offset': -1, 'checked': 0, 'valid': 0, 'failed': 0, 'compressed_bytes': 0}
        started = time.monotonic()

        def save(phase):
            for role, checkpoint in checkpoints.items():
                audit.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?)', (role, json.dumps(checkpoint)))
            audit.commit()
            state.update(phase=phase, archives=checkpoints, checked_images=sum(c['checked'] for c in checkpoints.values()),
                         valid_images=sum(c['valid'] for c in checkpoints.values()),
                         failed_images=sum(c['failed'] for c in checkpoints.values()),
                         compressed_bytes_checked=sum(c['compressed_bytes'] for c in checkpoints.values()),
                         run_elapsed_seconds=round(time.monotonic()-started, 1),
                         updated_utc=datetime.now(timezone.utc).isoformat())
            write_status(output/'status.json', state)

        save('running')
        try:
            for role, reader in readers.items():
                checkpoint = checkpoints[role]
                rows = source.execute('SELECT * FROM members WHERE role=? AND (disk>? OR (disk=? AND offset>?)) ORDER BY disk,offset',
                                      (role, checkpoint['disk'], checkpoint['disk'], checkpoint['offset']))
                state['active_archive'] = role
                for row in rows:
                    error = verify_member(reader, entry_from_row(row))
                    if error:
                        audit.execute('INSERT OR REPLACE INTO failures VALUES(?,?,?,?,?,?)',
                                      (role, row['key'], row['name'], row['disk'], row['offset'], error))
                    checkpoint.update(disk=row['disk'], offset=row['offset'])
                    checkpoint['checked'] += 1
                    checkpoint['valid' if error is None else 'failed'] += 1
                    checkpoint['compressed_bytes'] += row['compressed']
                    if checkpoint['checked'] % 100 == 0:
                        save('running')
                save('running')
            current = {role: [{'path': str(part), 'bytes': part.stat().st_size, 'mtime_ns': part.stat().st_mtime_ns}
                              for part in reader.parts] for role, reader in readers.items()}
            if current != fingerprint:
                raise ValueError('검사 도중 원본이 변경됐습니다. 완료로 간주하지 않습니다.')
            assert sum(c['checked'] for c in checkpoints.values()) == state['total_images']
            save('completed_with_failures' if state['failed_images'] else 'completed')
            (output/'summary.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf8')
            print('ARCHIVE_INTEGRITY_COMPLETE', json.dumps(state, ensure_ascii=False), flush=True)
        except BaseException as exc:
            state.update(error=str(exc), traceback=traceback.format_exc())
            save('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
        finally:
            for reader in readers.values():
                reader.close()
            source.close()
            audit.close()


if __name__ == '__main__':
    main()
