"""Run the AI Hub 71330 preprocessing workflow or generate a local demo."""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from getpass import getpass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_WORK_DIR = SCRIPTS.parent / "data"
LABEL_KEY = "485847"
MIN_FREE_BYTES = 500_000_000


def create_demo(raw: Path) -> None:
    """Generate two synthetic image/label pairs matching the AI Hub schema."""
    raw.mkdir(parents=True, exist_ok=True)
    pixel = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVuoAAAAASUVORK5CYII="
    )
    for frame in range(1, 3):
        stem = f"demo_frame_{frame:02}"
        image_name = f"{stem}.png"
        data = {
            "info": {"name": "synthetic-demo"},
            "categories": [{"id": 3, "name": "화염"}],
            "images": [{"id": 1, "width": 1, "height": 1, "file_name": image_name}],
            "annotations": [{
                "id": 1, "image_id": 1, "category_id": 3,
                "bbox": [0, 0, 1, 1], "segmentation": [[0, 0, 1, 0, 1, 1, 0, 1]],
                "area": 1, "iscrowd": 0,
            }] if frame == 1 else [],
        }
        (raw / image_name).write_bytes(pixel)
        (raw / f"{stem}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def download_labels(raw: Path) -> None:
    if not sys.platform.startswith("linux") or not shutil.which("bash"):
        raise SystemExit("AI Hub 다운로드는 WSL Ubuntu, Linux 또는 Colab에서 실행하세요.")
    raw.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(raw).free < MIN_FREE_BYTES:
        raise SystemExit("검증 라벨 다운로드 및 압축 해제에 최소 500MB 여유 공간이 필요합니다.")
    key = os.environ.get("AIHUB_API_KEY") or getpass("AI Hub API key: ").strip()
    if not key:
        raise SystemExit("AI Hub API 키를 입력하세요.")
    subprocess.run(
        ["bash", str(SCRIPTS / "download_aihub.sh"), LABEL_KEY],
        env={**os.environ, "AIHUB_API_KEY": key, "AIHUB_DATA_DIR": str(raw)},
        check=True,
    )
    if not next(raw.rglob("*.json"), None):
        raise SystemExit("다운로드 폴더에서 라벨 JSON을 찾지 못했습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("demo", "download-labels", "local"))
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--input", type=Path, help="압축을 푼 이미지/라벨 폴더 (local 모드)")
    parser.add_argument("--output", type=Path, help="전처리 결과 폴더")
    args = parser.parse_args()
    if (args.mode == "local") != (args.input is not None):
        parser.error("local 모드에서만 --input을 지정해야 합니다.")

    work = args.work_dir.resolve()
    raw = args.input.resolve() if args.input else work / args.mode / "raw"
    output = args.output.resolve() if args.output else work / args.mode / "processed"
    if raw == output or raw in output.parents or output in raw.parents:
        parser.error("입력 폴더와 결과 폴더는 서로 다른 위치로 지정하세요.")
    if args.mode == "demo":
        create_demo(raw)
    elif args.mode == "download-labels":
        download_labels(raw)
    if not next(raw.rglob("*.json"), None):
        raise SystemExit(f"라벨 JSON을 찾지 못했습니다: {raw}")

    subprocess.run(
        [sys.executable, str(SCRIPTS / "preprocess_aihub.py"),
         "--data-dir", str(raw), "--output-dir", str(output)],
        check=True,
    )


if __name__ == "__main__":
    main()
