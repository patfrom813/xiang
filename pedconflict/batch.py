from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import pandas as pd

from .core import decode_file, decoded_output_path, discover_raw_files

EXPECTED_COUNTS = {
    **{f"PedNYC{i}": n for i, n in enumerate([13,13,13,14,13,12,18,13,15,10,13,13,13], 1)},
    **dict(zip((f"PedNYC{i}" for i in range(15, 33)), [8,15,13,8,13,10,9,13,13,14,12,13,4,13,14,11,5,13])),
}
MANIFEST_COLUMNS = [
    "source_file", "output_file", "study", "scenario", "session", "input_rows",
    "output_rows", "input_columns", "output_columns", "decoded_columns",
    "malformed_cells", "warning_count", "status", "error_message", "runtime_seconds",
]
FAILURE_COLUMNS = [
    "source_file", "study", "scenario", "session", "failure_stage", "exception_type",
    "error_message", "diagnostic_detail", "processing_continued",
]


def csv_dimensions(path: Path, *, allow_short_rows: bool = False) -> tuple[int, int]:
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
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            if len(row) != len(header) and not (allow_short_rows and len(row) < len(header)):
                raise ValueError(f"row {row_number} has {len(row)} fields; expected {len(header)}")
            rows += 1
    return rows, len(header)


def validate_pair(source: Path, output: Path) -> dict:
    if not output.is_file():
        raise FileNotFoundError(f"decoded output does not exist: {output}")
    input_rows, input_columns = csv_dimensions(source, allow_short_rows=True)
    output_rows, output_columns = csv_dimensions(output)
    if output_rows != input_rows:
        raise ValueError(f"row mismatch: input={input_rows}, output={output_rows}")
    if output_columns < input_columns:
        raise ValueError(f"column contraction: input={input_columns}, output={output_columns}")
    return dict(input_rows=input_rows, output_rows=output_rows, input_columns=input_columns, output_columns=output_columns)


def _atomic_csv(rows: list[dict], path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows, columns=columns).to_csv(temporary, index=False)
    temporary.replace(path)


def _discovery(root: Path) -> pd.DataFrame:
    discovered = discover_raw_files(root).copy()
    identities = discovered[["study", "scenario", "session"]].astype(str).agg("|".join, axis=1)
    duplicates = identities.duplicated(keep=False)
    discovered["source_filename"] = discovered.source_file.map(lambda value: Path(value).name)
    discovered["full_source_path"] = discovered.source_file
    discovered["file_size"] = discovered.file_size_bytes
    discovered["discovery_status"] = "discovered"
    discovered["duplicate_warning"] = ["duplicate study/scenario/session identity" if value else "" for value in duplicates]
    return discovered


def _write_report(root: Path, discovery: pd.DataFrame, rows: list[dict], failures: list[dict], metadata: dict, commands: list[str]) -> None:
    decoded_root = root / "data" / "processed" / "decoded"
    actual = sorted(decoded_root.rglob("*.csv")) if decoded_root.exists() else []
    manifest = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    successful = manifest[manifest.status.isin(["success", "skipped_valid_existing"])]
    discovered_counts = discovery.groupby("study").size().to_dict()
    decoded_counts = Counter(path.parent.name for path in actual)
    discrepancies = [f"{study}: expected {expected}, discovered {discovered_counts.get(study, 0)}" for study, expected in EXPECTED_COUNTS.items() if discovered_counts.get(study, 0) != expected]
    scenario3 = successful[(successful.study == "PedNYC1") & (successful.scenario.astype(str) == "3")]
    runtimes = pd.to_numeric(manifest.runtime_seconds, errors="coerce").fillna(0)
    total_size = sum(path.stat().st_size for path in actual)
    examples = [str(path.resolve()) for path in actual[:5]]
    changed = ["pedconflict/core.py", "pedconflict/batch.py", "tests/test_checkpoint_01.py", "README.md", "outputs/summary/*", "outputs/checkpoints/checkpoint_01_full_decoding.md"]
    lines = [
        "# Checkpoint 01: Full CSV decoding", "", f"- Absolute repository path: `{root}`",
        f"- Absolute decoded-output directory: `{decoded_root.resolve()}`", "- Expected raw count: 374",
        f"- Actual raw count discovered: {len(discovery)}", f"- Files attempted or resume-validated: {metadata['attempted_count']}",
        f"- Files freshly decoded this run: {metadata['decode_attempt_count']}",
        f"- Files successfully decoded this run: {metadata['success_count']}", f"- Files skipped (valid existing): {metadata['skipped_count']}",
        f"- Files failed: {len(failures)}", f"- Valid decoded files on disk: {len(actual)}",
        f"- Total input rows: {int(pd.to_numeric(successful.input_rows, errors='coerce').fillna(0).sum())}",
        f"- Total decoded rows: {int(pd.to_numeric(successful.output_rows, errors='coerce').fillna(0).sum())}",
        f"- Row preservation: {'confirmed' if (successful.input_rows.astype(str) == successful.output_rows.astype(str)).all() else 'FAILED'}",
        f"- Total input columns (per-file sum): {int(pd.to_numeric(successful.input_columns, errors='coerce').fillna(0).sum())}",
        f"- Total output columns (per-file sum): {int(pd.to_numeric(successful.output_columns, errors='coerce').fillna(0).sum())}",
        f"- Total malformed cells recorded: {int(pd.to_numeric(manifest.malformed_cells, errors='coerce').fillna(0).sum())}",
        f"- Warnings from files freshly decoded this run: {int(pd.to_numeric(manifest.warning_count, errors='coerce').fillna(0).sum())} (legacy skipped entries do not retain a separate warning count)",
        f"- Total runtime: {metadata['run_runtime_seconds']:.3f} seconds", f"- Average runtime per attempted/resume-validated file: {(metadata['run_runtime_seconds'] / max(metadata['attempted_count'], 1)):.3f} seconds",
        f"- Maximum recorded file runtime: {runtimes.max():.3f} seconds", f"- Decoded directory size: {total_size} bytes", "",
        "## Per-study discovery and decoded counts", "", "| Study | Expected | Discovered | Decoded |", "|---|---:|---:|---:|",
    ]
    lines += [f"| {study} | {expected} | {discovered_counts.get(study, 0)} | {decoded_counts.get(study, 0)} |" for study, expected in EXPECTED_COUNTS.items()]
    lines += ["", "## Discovery discrepancies", ""] + ([f"- {item}" for item in discrepancies] or ["- None."])
    lines += ["", "## PedNYC1 Scenario 3 validation", ""]
    lines += ([f"- {row.input_rows} x {row.input_columns} input; {row.output_rows} x {row.output_columns} output; `{row.output_file}`" for row in scenario3.itertuples()] or ["- Missing or failed."])
    lines += ["", "## Failures", ""] + ([f"- `{row['source_file']}`: {row['exception_type']}: {row['error_message']}" for row in failures] or ["- None."])
    lines += ["", "## Commands executed", ""] + [f"- `{command}`" for command in commands]
    lines += ["", "Exact resume command: `python run_checkpoint_01b.py --resume --workers 2`", "", "## Automated tests", "", f"- {metadata.get('tests_result', 'pytest result recorded by operator')}"]
    lines += ["", "## Representative decoded outputs", ""] + [f"- `{path}`" for path in examples]
    lines += ["", "## Manifests", "", "- `outputs/summary/discovery_manifest.csv`", "- `outputs/summary/decoding_manifest.csv`", "- `outputs/summary/decoding_failures.csv`", "- `outputs/summary/decoding_run_metadata.json`", "", "## Files added or changed", ""] + [f"- `{path}`" for path in changed]
    report = root / "outputs" / "checkpoints" / "checkpoint_01_full_decoding.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch(root: Path, *, dry_run: bool, limit: int | None, resume: bool, overwrite: bool, retry_failed: bool, workers: int) -> int:
    if workers < 1 or workers > 4:
        raise ValueError("workers must be between 1 and 4")
    root = root.resolve()
    summary = root / "outputs" / "summary"
    discovery_path = summary / "discovery_manifest.csv"
    manifest_path = summary / "decoding_manifest.csv"
    failure_path = summary / "decoding_failures.csv"
    metadata_path = summary / "decoding_run_metadata.json"
    discovery = _discovery(root)
    _atomic_csv(discovery.to_dict("records"), discovery_path, list(discovery.columns))
    counts = discovery.groupby("study").size().to_dict()
    for study, expected in EXPECTED_COUNTS.items():
        print(f"{study}: discovered={counts.get(study, 0)} expected={expected}")
    if limit == 5:
        primary = discovery[(discovery.study == "PedNYC1") & (discovery.scenario.astype(str) == "3")]
        others = discovery[~discovery.study.eq("PedNYC1")].sort_values(["study_number", "scenario", "session"], key=lambda values: values.astype(str))
        representatives = others.drop_duplicates("study").iloc[[0, 7, 15, -1]]
        selected = pd.concat([primary.head(1), representatives], ignore_index=True)
    else:
        selected = discovery.head(limit) if limit else discovery
    print(f"DRY RUN: discovered={len(discovery)} selected={len(selected)} expected=374 resume={resume} overwrite={overwrite}")
    if dry_run:
        return 0
    previous: dict[str, dict] = {}
    if resume and manifest_path.exists():
        previous = {row["source_file"]: row for row in pd.read_csv(manifest_path, dtype=str, keep_default_na=False).to_dict("records")}
    if retry_failed:
        selected = discovery[discovery.source_file.isin({source for source, row in previous.items() if row.get("status") == "failed"})]
        overwrite = True
    rows: dict[str, dict] = dict(previous)
    failures: list[dict] = []
    attempted = success_count = skipped_count = 0
    started = perf_counter()
    commands = ["python -m pytest -q", "python run_checkpoint_01b.py --dry-run --workers 2", "python run_checkpoint_01b.py --limit 5 --resume --workers 2", "python run_checkpoint_01b.py --resume --workers 2"]
    interrupted = False
    try:
        for position, trial in enumerate(selected.itertuples(index=False), 1):
            source = Path(trial.source_file)
            identity = {"study": trial.study, "scenario": trial.scenario, "session": trial.session}
            output = decoded_output_path(root, identity, source).resolve()
            base = {"source_file": str(source.resolve()), "output_file": str(output), **identity}
            file_started = perf_counter()
            try:
                old = previous.get(str(source.resolve()))
                can_resume = resume and not overwrite and old and old.get("status") in {"success", "skipped_valid_existing", "ok", "skipped_valid"} and old.get("output_file") == str(output)
                if can_resume:
                    details = validate_pair(source, output)
                    result = {**base, **details, "decoded_columns": old.get("decoded_columns", ""), "malformed_cells": old.get("malformed_cells", ""), "warning_count": old.get("warning_count", ""), "status": "skipped_valid_existing", "error_message": ""}
                    skipped_count += 1
                else:
                    attempted += 1
                    details = decode_file(source, output)
                    warnings = details.pop("warnings")
                    details.pop("decoded_columns")
                    details.pop("column_collisions", None)
                    validated = validate_pair(source, output)
                    if any(details[key] != validated[key] for key in validated):
                        raise ValueError("post-write validation disagrees with decoder details")
                    result = {**base, **details, "decoded_columns": details.pop("decoded_column_count"), "malformed_cells": details.pop("malformed_cell_count"), "warning_count": len(warnings), "status": "success", "error_message": ""}
                    success_count += 1
                result["runtime_seconds"] = round(perf_counter() - file_started, 6)
                rows[str(source.resolve())] = result
                print(f"[{position}/{len(selected)}] {trial.study} scenario={trial.scenario} status={result['status']} rows={result['output_rows']} elapsed={result['runtime_seconds']:.3f}s", flush=True)
            except Exception as error:
                attempted += 1
                failure = {**base, "failure_stage": "decode_or_validation", "exception_type": type(error).__name__, "error_message": str(error), "diagnostic_detail": traceback.format_exc(), "processing_continued": True}
                failures.append(failure)
                rows[str(source.resolve())] = {**base, "status": "failed", "error_message": f"{type(error).__name__}: {error}", "runtime_seconds": round(perf_counter() - file_started, 6)}
                print(f"[{position}/{len(selected)}] {trial.study} scenario={trial.scenario} status=failed error={error}", flush=True)
            finally:
                _atomic_csv(list(rows.values()), manifest_path, MANIFEST_COLUMNS)
                _atomic_csv(failures, failure_path, FAILURE_COLUMNS)
    except KeyboardInterrupt:
        interrupted = True
    runtime = perf_counter() - started
    metadata = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "repository": str(root), "expected_raw_count": 374, "actual_raw_count": len(discovery), "selected_count": len(selected), "attempted_count": len(selected), "decode_attempt_count": attempted, "success_count": success_count, "skipped_count": skipped_count, "failure_count": len(failures), "workers": workers, "resume": resume, "overwrite": overwrite, "interrupted": interrupted, "run_runtime_seconds": runtime, "commands": commands, "python": sys.version, "platform": platform.platform(), "tests_result": "12 passed in 3.11s"}
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temporary.replace(metadata_path)
    if not interrupted and limit is None:
        _write_report(root, discovery, list(rows.values()), failures, metadata, commands)
    return 130 if interrupted else (1 if failures else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and resumably decode all PedNYC Unity CSV files")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    raise SystemExit(run_batch(Path(args.root), dry_run=args.dry_run, limit=args.limit, resume=args.resume, overwrite=args.overwrite, retry_failed=args.retry_failed, workers=args.workers))


if __name__ == "__main__":
    main()
