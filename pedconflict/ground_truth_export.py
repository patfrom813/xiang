from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .core import discover_raw_files
from .driver_signals import parse_indicator_series, summarize_trial


PREDICTION_COLUMNS = [
    "StudyFolder",
    "ScenarioName",
    "Did the driver signal",
    "How does vehicle speed change?",
    "How does pedestrian speed change?",
    "Who has the right of way?（Who reached the intersection first?）",
    "Who went first？",
    "Did the pedestrian use hand gestures?",
]
SIGNAL_LABELS = {
    "signaled_left": "Signaled left",
    "signaled_right": "Signaled right",
    "both_active_or_hazards": "Signaled both",
    "did_not_signal": "Did not signal",
    "unknown": "Unknown",
}
ORDER_LABELS = {
    "pedestrian_first": "Pedestrian",
    "vehicle_first": "Vehicle",
    "simultaneous_or_contested": "Same time",
    "not_applicable": "Neither",
    "indeterminate": "Unknown",
    "": "Unknown",
}
SPEED_LABELS = [
    "Stopped", "Slowed down", "Sped up", "Maintained speed",
    "Slowed down then sped up", "Sped up then slowed down",
    "Multiple changes", "Unknown",
]


@dataclass(frozen=True)
class Rules:
    near_stop_mps: float = 0.15
    vehicle_slowing_mps2: float = -0.25
    vehicle_speeding_mps2: float = 0.35
    pedestrian_slowing_mps2: float = -0.25
    pedestrian_speeding_mps2: float = 0.25
    minimum_event_duration_sec: float = 0.50
    event_gap_merge_sec: float = 0.25
    signal_minimum_frames: int = 2
    signal_minimum_duration_sec: float = 0.10
    signal_blink_gap_sec: float = 0.75
    arrival_tie_tolerance_sec: float = 0.10
    passage_tie_tolerance_sec: float = 0.10
    conflict_occupancy_frames: int = 3
    gesture_minimum_duration_sec: float = 0.50


def natural_key(study: str, scenario: str | int) -> tuple[int, int]:
    study_match = re.search(r"(\d+)$", str(study))
    scenario_match = re.search(r"(\d+)$", str(scenario))
    return (
        int(study_match.group(1)) if study_match else 10**9,
        int(scenario_match.group(1)) if scenario_match else 10**9,
    )


def _number(value: object) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else math.nan
    except (TypeError, ValueError):
        return math.nan


def _intervals(times: np.ndarray, active: np.ndarray, minimum: float, merge_gap: float) -> list[tuple[float, float]]:
    runs: list[tuple[float, float]] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(active) - 1):
            stop = index if value and index == len(active) - 1 else index - 1
            if times[stop] - times[start] >= minimum:
                runs.append((float(times[start]), float(times[stop])))
            start = None
    merged: list[tuple[float, float]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def classify_speed(
    frame: pd.DataFrame,
    *,
    actor: str,
    rules: Rules,
    window: tuple[float, float] | None = None,
) -> dict:
    prefix = "car" if actor == "vehicle" else "ped"
    speed_column = f"{prefix}_speed_xz_smooth"
    accel_column = f"{prefix}_accel_xz"
    required = {"ScenarioTime_sec", speed_column, accel_column}
    if not required.issubset(frame.columns):
        return {"prediction": "Unknown", "initial": math.nan, "minimum": math.nan, "maximum": math.nan,
                "final": math.nan, "sequence": "", "confidence": "unavailable", "evidence": "missing motion columns"}
    data = pd.DataFrame({
        "time": pd.to_numeric(frame["ScenarioTime_sec"], errors="coerce"),
        "speed": pd.to_numeric(frame[speed_column], errors="coerce"),
        "accel": pd.to_numeric(frame[accel_column], errors="coerce"),
    }).dropna(subset=["time", "speed"])
    if window is not None and all(math.isfinite(value) for value in window):
        margin = 3.0
        subset = data[(data.time >= window[0] - margin) & (data.time <= window[1] + margin)]
        if len(subset) >= 10:
            data = subset
    elif actor == "pedestrian" and len(data):
        moving = data.index[data.speed >= 0.30]
        if len(moving):
            first = moving[0]
            data = data.loc[max(data.index.min(), first - 5):]
    if len(data) < 10 or data.speed.notna().mean() < 0.8:
        return {"prediction": "Unknown", "initial": math.nan, "minimum": math.nan, "maximum": math.nan,
                "final": math.nan, "sequence": "", "confidence": "unavailable", "evidence": "insufficient valid motion samples"}
    times = data.time.to_numpy(float)
    speed = data.speed.to_numpy(float)
    accel = data.accel.to_numpy(float)
    slow_threshold = rules.vehicle_slowing_mps2 if actor == "vehicle" else rules.pedestrian_slowing_mps2
    fast_threshold = rules.vehicle_speeding_mps2 if actor == "vehicle" else rules.pedestrian_speeding_mps2
    slowing = _intervals(times, np.isfinite(accel) & (accel <= slow_threshold),
                         rules.minimum_event_duration_sec, rules.event_gap_merge_sec)
    speeding = _intervals(times, np.isfinite(accel) & (accel >= fast_threshold),
                          rules.minimum_event_duration_sec, rules.event_gap_merge_sec)
    events = sorted([(start, end, "slowed") for start, end in slowing] +
                    [(start, end, "sped_up") for start, end in speeding])
    sequence: list[str] = []
    for _, _, label in events:
        if not sequence or sequence[-1] != label:
            sequence.append(label)
    tail_count = max(3, int(len(speed) * 0.10))
    stopped = bool(np.nanmedian(speed[-tail_count:]) < rules.near_stop_mps and
                   np.nanmedian(speed[:tail_count]) >= rules.near_stop_mps)
    if stopped and (not sequence or sequence[-1] == "slowed"):
        prediction = "Stopped"
    elif sequence == ["slowed"]:
        prediction = "Slowed down"
    elif sequence == ["sped_up"]:
        prediction = "Sped up"
    elif sequence == ["slowed", "sped_up"]:
        prediction = "Slowed down then sped up"
    elif sequence == ["sped_up", "slowed"]:
        prediction = "Sped up then slowed down"
    elif len(sequence) > 2:
        prediction = "Multiple changes"
    else:
        prediction = "Maintained speed"
    confidence = "high" if len(data) >= 100 and (events or prediction == "Maintained speed") else "medium"
    return {
        "prediction": prediction,
        "initial": float(np.nanmedian(speed[:tail_count])),
        "minimum": float(np.nanmin(speed)),
        "maximum": float(np.nanmax(speed)),
        "final": float(np.nanmedian(speed[-tail_count:])),
        "sequence": "|".join(f"{label}:{start:.3f}-{end:.3f}" for start, end, label in events),
        "confidence": confidence,
        "evidence": f"samples={len(data)}; window={times[0]:.3f}-{times[-1]:.3f}",
    }


def choose_representations(discovery: pd.DataFrame, root: Path) -> tuple[dict[tuple[str, int], dict], set[str]]:
    candidates: dict[tuple[str, int], list[dict]] = {}
    for trial in discovery.itertuples(index=False):
        if trial.scenario == "practice":
            continue
        source = Path(trial.source_file)
        feature = root / "data" / "processed" / "features" / trial.study / f"{source.stem}_features.csv"
        score = (int(feature.exists()), feature.stat().st_size if feature.exists() else 0, str(trial.session))
        row = {**trial._asdict(), "feature_file": str(feature), "selection_score": score}
        candidates.setdefault((trial.study, int(trial.scenario)), []).append(row)
    selected: dict[tuple[str, int], dict] = {}
    duplicates: set[str] = set()
    for key, rows in candidates.items():
        rows.sort(key=lambda row: row["selection_score"], reverse=True)
        selected[key] = rows[0]
        duplicates.update(str(row["source_file"]) for row in rows[1:])
    return selected, duplicates


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unavailable"


def _order(value: object) -> str:
    return ORDER_LABELS.get(str(value).strip(), "Unknown")


def run_export(root: Path, *, studies: set[int] | None = None) -> dict:
    root = root.resolve()
    output = root / "outputs" / "ground_truth_validation"
    output.mkdir(parents=True, exist_ok=True)
    rules = Rules()
    discovery = discover_raw_files(root)
    selected, duplicate_sources = choose_representations(discovery, root)
    outcomes_path = root / "outputs" / "summary" / "trial_outcomes.csv"
    outcomes = pd.read_csv(outcomes_path, dtype=str, keep_default_na=False)
    outcomes_by_source = {str(Path(row.source_file).resolve()): row._asdict() for row in outcomes.itertuples(index=False)}
    gesture_path = root / "outputs" / "summary" / "gesture_events.csv"
    gestures = pd.read_csv(gesture_path, dtype=str, keep_default_na=False)
    gestures["duration_number"] = pd.to_numeric(gestures.duration, errors="coerce")
    gesture_by_source = {str(Path(source).resolve()): group for source, group in gestures.groupby("source_file")}
    manifest: list[dict] = []
    predictions: list[dict] = []
    audits: list[dict] = []
    failures: list[dict] = []
    selected_sources = {str(Path(row["source_file"]).resolve()) for row in selected.values()}

    for trial in discovery.itertuples(index=False):
        source = str(Path(trial.source_file).resolve())
        feature = root / "data" / "processed" / "features" / trial.study / f"{Path(source).stem}_features.csv"
        graph = root / "outputs" / "trials" / trial.study / (
            "practice" if trial.scenario == "practice" else f"scenario_{trial.scenario}") / str(trial.session)
        status, reason = "selected", ""
        if trial.scenario == "practice":
            status, reason = "excluded", "practice trial"
        elif source in duplicate_sources:
            status, reason = "duplicate", "non-selected duplicate representation"
        elif studies is not None and int(trial.study_number) not in studies:
            status, reason = "excluded", "outside requested study subset"
        manifest.append({
            "StudyFolder": trial.study,
            "ScenarioName": "practice" if trial.scenario == "practice" else f"scenario{trial.scenario}",
            "source_file": source,
            "processed_feature_file": str(feature.resolve()),
            "matching_graph_output_directory": str(graph.resolve()),
            "processing_status": status,
            "exclusion_reason": reason,
        })

    keys = sorted(selected, key=lambda key: natural_key(*key))
    for study, scenario in keys:
        if studies is not None and int(re.search(r"\d+$", study).group()) not in studies:
            continue
        trial = selected[(study, scenario)]
        source = str(Path(trial["source_file"]).resolve())
        outcome = outcomes_by_source.get(source, {})
        feature_path = Path(trial["feature_file"])
        flags: list[str] = []
        notes: list[str] = []
        if feature_path.exists():
            frame = pd.read_csv(feature_path, dtype=str, keep_default_na=False, low_memory=False)
            frame.columns = [str(column).strip() for column in frame.columns]
        else:
            frame = pd.DataFrame()
            flags.append("missing_feature_file")
        if not frame.empty and "A_indicators" in frame and "ScenarioTime_sec" in frame:
            parsed = parse_indicator_series(frame["A_indicators"])
            signal_summary, intervals = summarize_trial(pd.to_numeric(frame["ScenarioTime_sec"], errors="coerce"), parsed)
            signal = SIGNAL_LABELS[signal_summary["driver_signal_result"]]
            signal_evidence = (
                f"left={[(x.start, x.end) for x in intervals['left']]};"
                f"right={[(x.start, x.end) for x in intervals['right']]};"
                f"quality={signal_summary['indicator_data_quality']}"
            )
            signal_confidence = "high" if signal != "Unknown" else "unavailable"
        else:
            signal, signal_evidence, signal_confidence = "Unknown", "missing indicator/time data", "unavailable"
        entry_values = [_number(outcome.get("car_zone_entry_time")), _number(outcome.get("ped_zone_entry_time"))]
        exit_values = [_number(outcome.get("car_zone_exit_time")), _number(outcome.get("ped_zone_exit_time"))]
        finite_times = [value for value in entry_values + exit_values if math.isfinite(value)]
        window = (min(finite_times), max(finite_times)) if finite_times else None
        vehicle = classify_speed(frame, actor="vehicle", rules=rules, window=window)
        pedestrian = classify_speed(frame, actor="pedestrian", rules=rules, window=window)
        arrival = _order(outcome.get("arrival_order", ""))
        passage = _order(outcome.get("passage_order", ""))
        if not outcome:
            flags.append("missing_trial_outcome")
        ped_entry = _number(outcome.get("ped_zone_entry_time"))
        car_entry = _number(outcome.get("car_zone_entry_time"))
        ped_pass = _number(outcome.get("ped_conflict_crossing_time"))
        car_pass = _number(outcome.get("car_conflict_crossing_time"))
        if arrival == "Neither":
            arrival_confidence = "high"
        elif arrival == "Unknown":
            arrival_confidence = "unavailable"
        else:
            arrival_confidence = "high" if math.isfinite(ped_entry) and math.isfinite(car_entry) else "low"
        passage_confidence = "unavailable" if passage == "Unknown" else "high"
        trial_gestures = gesture_by_source.get(source)
        if feature_path.exists() and trial_gestures is not None:
            ped_events = trial_gestures[
                (trial_gestures.actor == "pedestrian") &
                (trial_gestures.gesture_candidate.str.casefold() == "true") &
                (trial_gestures.duration_number >= rules.gesture_minimum_duration_sec)
            ]
            gesture = "Yes" if len(ped_events) else "No"
            gesture_confidence = "medium" if len(ped_events) else "medium"
            gesture_times = "|".join(
                f"{row.side}:{row.start_time}-{row.end_time}" for row in ped_events.itertuples(index=False)
            )
        elif feature_path.exists():
            ped_events = pd.DataFrame()
            gesture, gesture_confidence, gesture_times = "No", "low", ""
            notes.append("no gesture event rows; valid processed feature file")
        else:
            ped_events = pd.DataFrame()
            gesture, gesture_confidence, gesture_times = "Unknown", "unavailable", ""
        processing_status = "processed" if feature_path.exists() and outcome else "partial"
        if processing_status == "partial":
            failures.append({
                "StudyFolder": study, "ScenarioName": f"scenario{scenario}", "source_file": source,
                "failure_stage": "existing_processed_artifacts",
                "reason": "|".join(flags) or "required processed artifact unavailable",
            })
        prediction = dict(zip(PREDICTION_COLUMNS, [
            study, f"scenario{scenario}", signal, vehicle["prediction"], pedestrian["prediction"],
            arrival, passage, gesture,
        ]))
        predictions.append(prediction)
        audits.append({
            "StudyFolder": study,
            "ScenarioName": f"scenario{scenario}",
            "source_file": source,
            "driver_signal_prediction": signal,
            "driver_signal_evidence": signal_evidence,
            "driver_signal_confidence": signal_confidence,
            "vehicle_speed_prediction": vehicle["prediction"],
            "vehicle_speed_initial": vehicle["initial"],
            "vehicle_speed_min": vehicle["minimum"],
            "vehicle_speed_max": vehicle["maximum"],
            "vehicle_speed_final": vehicle["final"],
            "vehicle_speed_event_sequence": vehicle["sequence"],
            "vehicle_speed_confidence": vehicle["confidence"],
            "pedestrian_speed_prediction": pedestrian["prediction"],
            "pedestrian_speed_initial": pedestrian["initial"],
            "pedestrian_speed_min": pedestrian["minimum"],
            "pedestrian_speed_max": pedestrian["maximum"],
            "pedestrian_speed_final": pedestrian["final"],
            "pedestrian_speed_event_sequence": pedestrian["sequence"],
            "pedestrian_speed_confidence": pedestrian["confidence"],
            "pedestrian_conflict_entry_time": ped_entry,
            "vehicle_conflict_entry_time": car_entry,
            "arrival_time_difference": ped_entry - car_entry if math.isfinite(ped_entry) and math.isfinite(car_entry) else math.nan,
            "arrival_order_prediction": arrival,
            "arrival_order_confidence": arrival_confidence,
            "pedestrian_passage_time": ped_pass,
            "vehicle_passage_time": car_pass,
            "passage_time_difference": ped_pass - car_pass if math.isfinite(ped_pass) and math.isfinite(car_pass) else math.nan,
            "passage_order_prediction": passage,
            "passage_order_confidence": passage_confidence,
            "pedestrian_conflict_exit_time": _number(outcome.get("ped_zone_exit_time")),
            "vehicle_conflict_exit_time": _number(outcome.get("car_zone_exit_time")),
            "pedestrian_gesture_prediction": gesture,
            "gesture_event_count": len(ped_events),
            "gesture_event_times": gesture_times,
            "pedestrian_gesture_confidence": gesture_confidence,
            "data_quality_flags": "|".join(flags + ([outcome.get("data_quality_flags")] if outcome.get("data_quality_flags") else [])),
            "processing_status": processing_status,
            "notes": "|".join(notes),
        })

    prediction_frame = pd.DataFrame(predictions, columns=PREDICTION_COLUMNS)
    audit_frame = pd.DataFrame(audits)
    manifest_frame = pd.DataFrame(manifest)
    failure_frame = pd.DataFrame(failures, columns=["StudyFolder", "ScenarioName", "source_file", "failure_stage", "reason"])
    prediction_frame.to_csv(output / "xc_ped_algorithm_predictions.csv", index=False, encoding="utf-8-sig")
    audit_frame.to_csv(output / "xc_ped_algorithm_predictions_audit.csv", index=False, encoding="utf-8-sig")
    manifest_frame.to_csv(output / "trial_manifest.csv", index=False, encoding="utf-8-sig")
    failure_frame.to_csv(output / "failures.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_export": _git_commit(root),
        "ground_truth_dependency": False,
        "rules": asdict(rules),
        "allowed_output_labels": {
            "driver_signal": list(SIGNAL_LABELS.values()),
            "speed_change": SPEED_LABELS,
            "order": ["Pedestrian", "Vehicle", "Same time", "Neither", "Unknown"],
            "pedestrian_gesture": ["Yes", "No", "Unknown"],
        },
        "source_columns": {
            "vehicle_position": ["A VR Pos X", "A VR Pos Z"],
            "pedestrian_position": ["B VR Pos X", "B VR Pos Z"],
            "driver_indicator": "A indicators",
            "vehicle_features": ["car_speed_xz_smooth", "car_accel_xz"],
            "pedestrian_features": ["ped_speed_xz_smooth", "ped_accel_xz"],
        },
        "smoothing_settings": "reuses precomputed *_speed_xz_smooth and *_accel_xz columns; original generator source is absent",
        "conflict_zone_definitions": {
            "templates": "outputs/conflict_zones/templates/scenario_*.geojson",
            "vehicle_length_m": 4.5, "vehicle_width_m": 1.8,
            "pedestrian_radius_m": 0.35, "margin_m": 0.4,
        },
    }
    (output / "classification_rules.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    subset = "all requested studies" if studies is None else ",".join(map(str, sorted(studies)))
    readme = f"""# XC-Ped algorithm predictions

Generated independently from Xiang processed data for {subset}. Ground-truth answer columns are not an input.

## Prediction rules

- Driver signal: decoded `A indicators`, requiring two frames or 0.10 seconds and merging blink gaps up to 0.75 seconds.
- Vehicle and pedestrian speed: precomputed X/Z smoothed speed and acceleration, classified from sustained 0.50-second phases. The pedestrian window begins with meaningful walking where no conflict interval exists.
- The ground-truth “right of way” heading is interpreted only as conflict-zone boundary arrival order. It does not represent legal priority.
- Passage order uses the existing conflict-crossing calculation and is separate from arrival order; a participant may arrive first and yield.
- Pedestrian gesture is Yes only when an existing numerical pedestrian gesture candidate lasts at least 0.50 seconds. It does not assign communicative meaning.
- Driver hand gestures are excluded because the driver is not physically observable.

## Limitations

The source code that originally generated motion features, conflict geometry, and gesture events is absent from the current Git tree. This exporter therefore reuses the locked numerical artifacts. Trials missing those artifacts remain present with `Unknown` predictions and are listed in `failures.csv`.

Duplicate raw representations are resolved deterministically by preferring an existing feature file, then the largest feature file, then the latest session identifier. Every decision is retained in `trial_manifest.csv`.

## Rerun

```powershell
python scripts/export_ground_truth_predictions.py
```

## Future comparison

After predictions are locked, run:

```powershell
python scripts/evaluate_against_ground_truth.py --predictions outputs/ground_truth_validation/xc_ped_algorithm_predictions.csv --ground-truth PATH_TO_GROUND_TRUTH.csv
```

The evaluator joins only on `StudyFolder + ScenarioName`; it never joins by row number.
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    return {
        "prediction_rows": len(prediction_frame),
        "manifest_rows": len(manifest_frame),
        "failures": len(failure_frame),
        "duplicates_excluded": len(duplicate_sources),
        "output_directory": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ground-truth-independent XC-Ped trial predictions")
    parser.add_argument("--root", default=".")
    parser.add_argument("--studies", help="comma-separated study numbers, e.g. 1,2")
    args = parser.parse_args()
    studies = {int(value) for value in args.studies.split(",")} if args.studies else None
    print(json.dumps(run_export(Path(args.root), studies=studies), indent=2))


if __name__ == "__main__":
    main()
