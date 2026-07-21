from __future__ import annotations

import base64
import csv
import math
import re
import struct
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

RAW_PATTERN = "CSV_Scenario-*_Session-temp_*.csv"
RAW_RE = re.compile(
    r"^CSV_Scenario-(?:(?:Ped-(?P<scenario>\d+))|(?P<practice>Practice))_Session-(?P<session>.+)\.csv$",
    re.IGNORECASE,
)
STUDY_RE = re.compile(r"^PedNYC(?P<number>\d+)$", re.IGNORECASE)
EXCLUDED_PARTS = {"processed", "output", "outputs"}


def parse_raw_path(path: Path) -> dict:
    """Parse study/scenario/session metadata from one raw-file path."""
    match = RAW_RE.match(path.name)
    study = next((part for part in reversed(path.parts) if STUDY_RE.match(part)), None)
    if not match or study is None:
        raise ValueError(f"Not a supported raw trial path: {path}")
    return {
        "study": study,
        "study_number": int(STUDY_RE.match(study).group("number")),
        "scenario": int(match.group("scenario")) if match.group("scenario") else "Practice",
        "session": match.group("session"),
    }


def discover_raw_files(root: Path) -> pd.DataFrame:
    """Return a stable, duplicate-free manifest for all raw trial CSVs."""
    root = root.resolve()
    records: dict[str, dict] = {}
    for path in sorted(root.rglob(RAW_PATTERN), key=lambda p: str(p).casefold()):
        relative = path.resolve().relative_to(root)
        if any(part.casefold() in EXCLUDED_PARTS for part in relative.parts):
            continue
        try:
            parsed = parse_raw_path(relative)
        except ValueError:
            continue
        if parsed["study_number"] == 14 or not (1 <= parsed["study_number"] <= 32):
            continue
        stat = path.stat()
        source = str(path.resolve())
        records[source.casefold()] = {
            "source_file": source,
            "source_relative": relative.as_posix(),
            **parsed,
            "file_size_bytes": stat.st_size,
            "modified_time_utc": pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").isoformat(),
        }
    columns = ["source_file", "source_relative", "study", "study_number", "scenario", "session", "file_size_bytes", "modified_time_utc"]
    return pd.DataFrame(sorted(records.values(), key=lambda r: r["source_relative"].casefold()), columns=columns)


def decode_float_array(value: object) -> tuple[float, ...]:
    if pd.isna(value) or not str(value).strip():
        raise ValueError("missing value")
    decoded = base64.b64decode(str(value), validate=True)
    if not decoded or len(decoded) % 4:
        raise ValueError("decoded byte length is not a positive multiple of four")
    values = struct.unpack("<" + "f" * (len(decoded) // 4), decoded)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("decoded array contains a non-finite value")
    return values


def _suffixes(length: int) -> list[str]:
    if length == 3:
        return [" X", " Y", " Z"]
    if length == 4:
        return [" X", " Y", " Z", " W"]
    return [f" {index}" for index in range(length)]


def decode_dataframe(frame: pd.DataFrame, sample_size: int = 20) -> tuple[pd.DataFrame, dict]:
    """Expand sampled Unity float arrays without removing or reordering rows."""
    frame = frame.copy()
    original_names = [str(name) for name in frame.columns]
    cleaned_names = [name[1:] if index == 0 and name.startswith("]") else name for index, name in enumerate(original_names)]
    collisions: list[str] = []
    seen: Counter[str] = Counter()
    unique_names: list[str] = []
    for original, cleaned in zip(original_names, cleaned_names):
        seen[cleaned] += 1
        if seen[cleaned] == 1:
            unique_names.append(cleaned)
        else:
            replacement = f"{cleaned}__duplicate_{seen[cleaned]}"
            collisions.append(f"cleaned column collision: {original!r} -> {cleaned!r}; retained as {replacement!r}")
            unique_names.append(replacement)
    frame.columns = unique_names
    output: dict[str, object] = {}
    decoded_names: list[str] = []
    malformed_cells = 0
    warnings: list[str] = list(collisions)
    for column in frame.columns:
        sample = frame[column][frame[column].notna() & frame[column].astype(str).str.len().gt(0)].head(sample_size)
        lengths: list[int] = []
        for value in sample:
            try:
                lengths.append(len(decode_float_array(value)))
            except (ValueError, TypeError):
                pass
        modal = Counter(lengths).most_common(1)[0][0] if lengths else None
        established = modal is not None and lengths.count(modal) >= max(2, math.ceil(len(sample) * 0.6))
        if not established:
            output[column] = frame[column].to_numpy()
            continue
        expanded = np.full((len(frame), modal), np.nan)
        for row_index, value in enumerate(frame[column]):
            try:
                values = decode_float_array(value)
                if len(values) != modal:
                    raise ValueError(f"length {len(values)} differs from modal length {modal}")
                expanded[row_index] = values
            except (ValueError, TypeError) as error:
                malformed_cells += 1
                warnings.append(f"{column} row {row_index}: {error}")
        for index, suffix in enumerate(_suffixes(modal)):
            output[column + suffix] = expanded[:, index]
        decoded_names.append(column)
    decoded = pd.DataFrame(output, index=frame.index)
    return decoded, {"decoded_column_count": len(decoded_names), "malformed_cell_count": malformed_cells, "decoded_columns": decoded_names, "warnings": warnings, "column_collisions": collisions}


def decoded_output_path(root: Path, metadata: dict, source: Path) -> Path:
    return root / "data" / "processed" / "decoded" / metadata["study"] / f"{source.stem}_decoded.csv"


def decode_file(source: Path, output: Path) -> dict:
    started = perf_counter()
    parse_warnings: list[str] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader)
        records = []
        for physical_row, record in enumerate(reader, start=2):
            if not record or (len(record) == 1 and not record[0].strip()):
                continue
            if len(record) < len(header):
                parse_warnings.append(f"raw row {physical_row}: padded {len(header) - len(record)} missing trailing fields")
                record = record + [""] * (len(header) - len(record))
            elif len(record) > len(header):
                raise ValueError(f"raw row {physical_row} has {len(record)} fields; expected {len(header)}")
            records.append(record)
    raw = pd.DataFrame(records, columns=header, dtype=str)
    decoded, details = decode_dataframe(raw)
    details["warnings"] = parse_warnings + details["warnings"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".tmp", prefix=output.name + ".", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            decoded.to_csv(handle, sep=";", index=False)
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {
        "input_rows": len(raw), "output_rows": len(decoded),
        "input_columns": len(raw.columns), "output_columns": len(decoded.columns),
        **details, "runtime_seconds": perf_counter() - started,
    }
