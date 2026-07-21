from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import pandas as pd

from .core import decode_file, decoded_output_path, discover_raw_files

MANIFEST_COLUMNS = [
    "source_file", "output_file", "study", "scenario", "session",
    "input_rows", "output_rows", "input_columns", "output_columns",
    "decoded_column_count", "malformed_cell_count", "status", "warnings",
    "error_message", "runtime_seconds", "completed_time_utc",
]


def csv_dimensions(path: Path) -> tuple[int, int]:
    """Validate a semicolon CSV and return data-row and header-column counts."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError("CSV is empty") from error
        if not header:
            raise ValueError("CSV has no header columns")
        rows = 0
        for row_number, row in enumerate(reader, start=2):
            if not row or (len(row) == 1 and row[0].strip() == ""):
                continue
            if len(row) != len(header):
                raise ValueError(f"row {row_number} has {len(row)} fields; expected {len(header)}")
            rows += 1
    return rows, len(header)


def validate_pair(source: Path, output: Path) -> dict:
    if not output.is_file():
        raise FileNotFoundError(f"decoded output does not exist: {output}")
    input_rows, input_columns = csv_dimensions(source)
    output_rows, output_columns = csv_dimensions(output)
    if output_rows != input_rows:
        raise ValueError(f"row mismatch: input={input_rows}, output={output_rows}")
    if output_columns < input_columns:
        raise ValueError(f"column contraction: input={input_columns}, output={output_columns}")
    return {"input_rows": input_rows, "output_rows": output_rows, "input_columns": input_columns, "output_columns": output_columns}


def _write_csv(rows: list[dict], path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def run_batch(root: Path, *, dry_run: bool, limit: int | None, resume: bool, overwrite: bool, workers: int) -> int:
    if workers != 1:
        raise ValueError("Checkpoint 1B currently enforces the conservative worker count --workers 1")
    root = root.resolve()
    checkpoint = root / "outputs" / "checkpoints"
    checkpoint.mkdir(parents=True, exist_ok=True)
    discovery_path = checkpoint / "checkpoint_01_discovery_manifest.csv"
    manifest_path = checkpoint / "checkpoint_01b_decoding_manifest.csv"
    failure_path = checkpoint / "checkpoint_01b_failure_manifest.csv"
    metadata_path = checkpoint / "checkpoint_01b_run_metadata.json"

    discovery = discover_raw_files(root)
    discovery.to_csv(discovery_path, index=False)
    selected = discovery.head(limit) if limit else discovery
    existing_rows: dict[str, dict] = {}
    if resume and manifest_path.exists():
        for row in pd.read_csv(manifest_path, dtype=str, keep_default_na=False).to_dict("records"):
            existing_rows[row["source_file"]] = row
    print(f"DRY RUN: {len(discovery)} authoritative files; {len(selected)} selected; resume={resume}; overwrite={overwrite}")
    if dry_run:
        return 0

    started = perf_counter()
    rows = list(existing_rows.values()) if resume else []
    failures: list[dict] = []
    interrupted = False
    try:
        for index, trial in enumerate(selected.itertuples(index=False), start=1):
            source = Path(trial.source_file)
            metadata = {"study": trial.study, "scenario": trial.scenario, "session": trial.session}
            output = decoded_output_path(root, metadata, source)
            print(f"[{index}/{len(selected)}] {trial.source_relative}", flush=True)
            file_started = perf_counter()
            row = {"source_file": str(source), "output_file": str(output), **metadata}
            try:
                if resume and not overwrite and output.exists():
                    details = validate_pair(source, output)
                    result = {**row, **details, "decoded_column_count": "", "malformed_cell_count": "", "status": "skipped_valid", "warnings": "existing output validated; malformed count unavailable without repeating decode", "error_message": ""}
                else:
                    details = decode_file(source, output)
                    warning_text = " | ".join(details.pop("warnings"))
                    details.pop("decoded_columns")
                    validated = validate_pair(source, output)
                    if any(details[key] != validated[key] for key in validated):
                        raise ValueError("post-write validation disagrees with decoder manifest details")
                    result = {**row, **details, "status": "ok", "warnings": warning_text, "error_message": ""}
                result["runtime_seconds"] = perf_counter() - file_started
                result["completed_time_utc"] = datetime.now(timezone.utc).isoformat()
                existing_rows[str(source)] = result
                rows = list(existing_rows.values())
                print(f"  {result['status']}: {result['input_rows']}x{result['input_columns']} -> {result['output_rows']}x{result['output_columns']} ({result['runtime_seconds']:.3f}s)", flush=True)
            except Exception as error:
                failure = {**row, "status": "failed", "error_type": type(error).__name__, "error_message": str(error), "traceback": traceback.format_exc(), "runtime_seconds": perf_counter() - file_started, "completed_time_utc": datetime.now(timezone.utc).isoformat()}
                failures.append(failure)
                existing_rows[str(source)] = {**row, "status": "failed", "warnings": "", "error_message": f"{type(error).__name__}: {error}", "runtime_seconds": failure["runtime_seconds"], "completed_time_utc": failure["completed_time_utc"]}
                rows = list(existing_rows.values())
                print(f"  FAILED: {type(error).__name__}: {error}", flush=True)
            finally:
                _write_csv(rows, manifest_path, MANIFEST_COLUMNS)
                _write_csv(failures, failure_path, ["source_file", "output_file", "study", "scenario", "session", "status", "error_type", "error_message", "traceback", "runtime_seconds", "completed_time_utc"])
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted; checkpoint manifests are current and the same command can resume.", file=sys.stderr)
    finally:
        metadata = {
            "checkpoint": "01B", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "command": " ".join(sys.argv), "authoritative_discovery_count": len(discovery),
            "selected_count": len(selected), "manifest_rows": len(existing_rows),
            "resume": resume, "overwrite": overwrite, "workers": workers,
            "interrupted": interrupted, "run_runtime_seconds": perf_counter() - started,
            "python": sys.version, "platform": platform.platform(),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return 130 if interrupted else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Checkpoint 1B: resumable full raw CSV decoding")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    raise SystemExit(run_batch(Path(args.root), dry_run=args.dry_run, limit=args.limit, resume=args.resume, overwrite=args.overwrite, workers=args.workers))


if __name__ == "__main__":
    main()
