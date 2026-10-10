"""Unified inspection history. No network access or third-party dependencies."""

import argparse
import csv
import hashlib
import io
import math
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE_FIELDS = [
    "cycle", "image", "expected_condition", "expected_type", "gemini_condition",
    "gemini_type", "confidence", "type_match", "destination", "description",
]
CAMERA_FIELDS = ["camera_frame", "camera_top_surface", "capture_seconds"]
FIELDS = BASE_FIELDS + CAMERA_FIELDS + ["inspection_source"]


def _read(path, source):
    if path.is_symlink():
        raise ValueError(f"Log must not be a symbolic link: {path}")
    if not path.exists():
        return [], None, None
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data:
        return [], [], digest
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    reader = csv.DictReader(io.StringIO(data.decode(encoding), newline=""))
    header = reader.fieldnames
    allowed = [BASE_FIELDS] if source == "Texture" else [BASE_FIELDS + CAMERA_FIELDS, FIELDS]
    if header not in allowed:
        raise ValueError(f"Unexpected CSV header in {path.name}; original file not changed.")
    rows = []
    for index, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Malformed CSV row {index} in {path.name}.")
        normalized = {field: row.get(field, "") for field in FIELDS}
        normalized["inspection_source"] = row.get("inspection_source") or source
        validate(normalized)
        rows.append(normalized)
    return rows, header, digest


def validate(row):
    if set(row) != set(FIELDS):
        raise ValueError("Inspection record fields do not match the unified schema.")
    if int(row["cycle"]) < 1:
        raise ValueError("Cycle must be positive.")
    confidence = float(row["confidence"])
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between 0 and 1.")
    if str(row["type_match"]).lower() not in ("true", "false"):
        raise ValueError("type_match must be True or False.")
    if row["inspection_source"] not in ("Texture", "Camera"):
        raise ValueError("Unknown inspection source.")
    if row["destination"] not in ("GOOD", "SCRAP"):
        raise ValueError("Unknown destination.")
    if row["expected_condition"] not in ("GOOD", "DEFECTIVE") or row["gemini_condition"] not in ("GOOD", "DEFECTIVE"):
        raise ValueError("Unknown inspection condition.")
    if row["capture_seconds"] != "":
        duration = float(row["capture_seconds"])
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Capture time must be nonnegative.")


def _signature(row):
    # Cycle numbers and image names repeat between runs. Preserve multiplicity.
    return tuple(str(row[field]) for field in BASE_FIELDS)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def merge_logs(data_directory):
    """Keep both originals backed up; migrate texture history exactly once."""
    data_directory = Path(data_directory).resolve()
    legacy = data_directory / "inspection_log.csv"
    target = data_directory / "camera_inspection_log.csv"
    old_rows, _, old_digest = _read(legacy, "Texture")
    camera_rows, header, target_digest = _read(target, "Camera")
    migrated = Counter(_signature(row) for row in camera_rows if row["inspection_source"] == "Texture")
    additions = []
    for row in old_rows:
        signature = _signature(row)
        if migrated[signature]:
            migrated[signature] -= 1
        else:
            additions.append(row)
    combined = additions + camera_rows
    summary = {"legacy_rows_added": len(additions), "total_rows": len(combined), "changed": False}
    if not additions and header == FIELDS:
        return summary
    data_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".inspection-", suffix=".csv", dir=data_directory)
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(combined)
            stream.flush()
            os.fsync(stream.fileno())
        verified, verified_header, _ = _read(temporary, "Camera")
        if verified_header != FIELDS or verified != combined:
            raise RuntimeError("Merged CSV verification failed; original files not changed.")
        if _digest(target) != target_digest or _digest(legacy) != old_digest:
            raise RuntimeError("Logs changed during migration. Stop production and retry.")
        backup = data_directory / "log_backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        if target.exists() or legacy.exists():
            backup.mkdir(parents=True, exist_ok=False)
            for original in (legacy, target):
                if original.exists():
                    shutil.copy2(original, backup / original.name)
            summary["backup_directory"] = str(backup)
        # Recheck after backups: never overwrite a detected concurrent append.
        if _digest(target) != target_digest or _digest(legacy) != old_digest:
            raise RuntimeError("Logs changed during backup. Stop production and retry.")
        os.replace(temporary, target)
        summary["changed"] = True
        return summary
    finally:
        if temporary.exists():
            temporary.unlink()


def append_record(path, row):
    """Append a camera record using the same schema as the historical merge."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Log must not be a symbolic link.")
    row = {field: str(row.get(field, "")) for field in FIELDS}
    validate(row)
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=FIELDS).writeheader()
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        if next(csv.reader(stream), None) != FIELDS:
            raise RuntimeError("Log schema needs migration. Stop production and run inspection_records.py.")
    with path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=FIELDS).writerow(row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge inspection history into the camera log without deleting originals.")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "neu_defect_data")
    parser.add_argument("--check", action="store_true", help="Validate existing logs without writing.")
    args = parser.parse_args()
    if args.check:
        for filename, source in (("inspection_log.csv", "Texture"), ("camera_inspection_log.csv", "Camera")):
            rows, _, _ = _read(args.data_dir / filename, source)
            print(f"{filename}: {len(rows)} valid records")
    else:
        print(merge_logs(args.data_dir))
