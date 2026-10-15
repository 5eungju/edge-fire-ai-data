"""Validate AI Hub wildfire image/annotation pairs and export CSV manifests."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def records(value: Any) -> list[dict[str, Any]]:
    """Normalize a record or list of records to a list of dictionaries."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields or ["message"], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"),
                        help="압축 해제한 이미지/JSON 폴더 (기본: data/raw)")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"),
                        help="CSV 결과 폴더 (기본: data/processed)")
    args = parser.parse_args()

    root = args.data_dir.resolve()
    out = args.output_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"데이터 폴더를 찾을 수 없습니다: {root}")
    out.mkdir(parents=True, exist_ok=True)

    image_paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    image_by_name: dict[str, Path] = {}
    for image in image_paths:
        image_by_name.setdefault(image.name.casefold(), image)

    image_rows: list[dict[str, Any]] = []
    annotation_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    json_paths = sorted(p for p in root.rglob("*.json") if p.is_file())

    for json_path in json_paths:
        try:
            with json_path.open(encoding="utf-8-sig") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("JSON 최상위 값이 object가 아닙니다")

            info = payload.get("info", {})
            environment = payload.get("environment", {})
            categories = {c.get("id"): c.get("name", "")
                          for c in records(payload.get("categories"))}
            image_records = records(payload.get("images"))
            annotation_records = records(payload.get("annotations"))

            # AI Hub 샘플은 이미지 1개와 여러 annotation을 갖는 COCO형 JSON입니다.
            # 이미지 목록이 생략된 JSON은 같은 stem의 이미지 파일을 매칭 후보로 둡니다.
            if not image_records:
                image_records = [{"file_name": json_path.with_suffix(".jpg").name}]
            for image in image_records:
                filename = str(image.get("file_name") or json_path.with_suffix(".jpg").name)
                matched = image_by_name.get(Path(filename).name.casefold())
                image_id = image.get("id")
                linked = [a for a in annotation_records
                          if image_id is None or a.get("image_id") == image_id]
                bad_bbox_count = 0
                width, height = image.get("width"), image.get("height")
                for ann in linked:
                    cid = ann.get("category_id")
                    class_name = categories.get(cid, str(cid if cid is not None else "unknown"))
                    class_counts[class_name] += 1
                    bbox = ann.get("bbox")
                    valid = isinstance(bbox, list) and len(bbox) == 4
                    if valid:
                        try:
                            x, y, w, h = map(float, bbox)
                            valid = x >= 0 and y >= 0 and w > 0 and h > 0
                            if width is not None and height is not None:
                                valid = valid and x + w <= float(width) + 1 and y + h <= float(height) + 1
                        except (TypeError, ValueError):
                            valid = False
                    if not valid:
                        bad_bbox_count += 1
                    annotation_rows.append({
                        "source_json": str(json_path.relative_to(root)),
                        "image_file": filename,
                        "annotation_id": ann.get("id"),
                        "category_id": cid,
                        "category_name": class_name,
                        "bbox_xywh": bbox,
                        "bbox_valid": valid,
                        "area": ann.get("area"),
                        "iscrowd": ann.get("iscrowd"),
                        "segmentation": ann.get("segmentation"),
                    })
                image_rows.append({
                    "image_file": filename,
                    "image_path": str(matched) if matched else "",
                    "label_path": str(json_path),
                    "matched": bool(matched),
                    "width": width,
                    "height": height,
                    "annotation_count": len(linked),
                    "invalid_bbox_count": bad_bbox_count,
                    "dataset_split": info.get("name", ""),
                    "weather": environment.get("weather", "") if isinstance(environment, dict) else "",
                    "device": environment.get("device", "") if isinstance(environment, dict) else "",
                })
        except Exception as exc:  # Keep processing other files; log the bad one.
            error_rows.append({"label_path": str(json_path), "error": str(exc)})

    write_csv(out / "image_manifest.csv", image_rows)
    write_csv(out / "annotations.csv", annotation_rows)
    write_csv(out / "invalid_json.csv", error_rows)
    summary = {
        "data_dir": str(root),
        "image_files_found": len(image_paths),
        "json_files_found": len(json_paths),
        "json_files_with_errors": len(error_rows),
        "image_records": len(image_rows),
        "matched_images": sum(bool(row["matched"]) for row in image_rows),
        "annotation_records": len(annotation_rows),
        "invalid_bbox_records": sum(not row["bbox_valid"] for row in annotation_rows),
        "annotation_counts_by_class": dict(class_counts),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {out}")


if __name__ == "__main__":
    main()
