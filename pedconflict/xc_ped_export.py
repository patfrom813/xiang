from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PREDICTION_COLUMNS = [
    "StudyFolder", "ScenarioName", "Did the driver signal",
    "How does vehicle speed change?", "How does pedestrian speed change?",
    "Who has the right of way?（Who reached the intersection first?）",
    "Who went first？", "Did the pedestrian use hand gestures?",
]


def natural_key(study: str, scenario: str) -> tuple[int, int]:
    return tuple(int(re.search(r"\d+", value).group()) for value in (study, scenario))


def _events(frame: pd.DataFrame, actor: str) -> tuple[str, str]:
    prefix = "car" if actor == "vehicle" else "ped"
    speed_name, accel_name = f"{prefix}_speed_xz_smooth", f"{prefix}_accel_xz"
    if not {"ScenarioTime_sec", speed_name, accel_name}.issubset(frame):
        return "Unknown", "missing feature columns"
    time = pd.to_numeric(frame.ScenarioTime_sec, errors="coerce").to_numpy(float)
    speed = pd.to_numeric(frame[speed_name], errors="coerce").to_numpy(float)
    accel = pd.to_numeric(frame[accel_name], errors="coerce").to_numpy(float)
    valid = np.isfinite(time) & np.isfinite(speed)
    time, speed, accel = time[valid], speed[valid], accel[valid]
    if len(time) < 10:
        return "Unknown", "insufficient samples"
    if actor == "pedestrian":
        moving = np.flatnonzero(speed >= 0.30)
        if len(moving):
            start = max(0, moving[0] - 5)
            time, speed, accel = time[start:], speed[start:], accel[start:]
    low, high = (-0.25, 0.35) if actor == "vehicle" else (-0.25, 0.25)
    phases = []
    for label, mask in (("Slowing down", accel <= low), ("Speeding up", accel >= high)):
        start = None
        for i, active in enumerate(mask):
            if active and start is None:
                start = i
            if start is not None and (not active or i == len(mask) - 1):
                end = i if active and i == len(mask) - 1 else i - 1
                if time[end] - time[start] >= 0.50:
                    phases.append((time[start], time[end], label))
                start = None
    phases.sort()
    sequence = []
    for phase in phases:
        if not sequence or sequence[-1] != phase[2]:
            sequence.append(phase[2])
    tail = max(3, len(speed) // 10)
    if np.nanmedian(speed[-tail:]) < 0.15 and np.nanmedian(speed[:tail]) >= 0.15:
        label = "Not moving" if actor == "vehicle" else "Not walking"
    elif sequence == ["Slowing down"]:
        label = "Slowing down"
    elif sequence == ["Speeding up"]:
        label = "Speeding up"
    elif not sequence:
        label = "No change"
    else:
        label = " then ".join(sequence)
    evidence = (
        f"initial={np.nanmedian(speed[:tail]):.3f};min={np.nanmin(speed):.3f};"
        f"max={np.nanmax(speed):.3f};final={np.nanmedian(speed[-tail:]):.3f};"
        f"events={'|'.join(f'{x[2]}:{x[0]:.3f}-{x[1]:.3f}' for x in phases)}"
    )
    return label, evidence


def _pick_trials(outcomes: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, list[dict]]:
    rows, excluded = [], []
    for (_, _), group in outcomes.groupby(["study", "scenario"], sort=False):
        ranked = []
        for index, row in group.iterrows():
            feature = root / "data" / "processed" / "features" / row.study / f"{Path(row.source_file).stem}_features.csv"
            ranked.append((int(feature.exists()), feature.stat().st_size if feature.exists() else 0, row.session, index))
        ranked.sort(reverse=True)
        rows.append(outcomes.loc[ranked[0][3]])
        for item in ranked[1:]:
            old = outcomes.loc[item[3]]
            excluded.append({"StudyFolder": old.study, "ScenarioName": str(old.scenario),
                             "source_file": old.source_file, "status": "duplicate",
                             "reason": "non-selected duplicate representation"})
    return pd.DataFrame(rows), excluded


def export_predictions(root: Path) -> dict:
    root = root.resolve()
    out = root / "outputs" / "ground_truth_validation"
    out.mkdir(parents=True, exist_ok=True)
    outcomes = pd.read_csv(root / "outputs" / "summary" / "trial_outcomes.csv",
                           dtype=str, keep_default_na=False)
    chosen, duplicate_manifest = _pick_trials(outcomes, root)
    duplicate_count = len(duplicate_manifest)
    gestures = pd.read_csv(root / "outputs" / "summary" / "gesture_events.csv",
                           dtype=str, keep_default_na=False)
    gestures["duration_num"] = pd.to_numeric(gestures.duration, errors="coerce")
    gesture_groups = {str(Path(key).resolve()): value for key, value in gestures.groupby("source_file")}
    predictions, audit, manifest, failures = [], [], duplicate_manifest, []
    for row in chosen.itertuples(index=False):
        source = str(Path(row.source_file).resolve())
        feature = root / "data" / "processed" / "features" / row.study / f"{Path(source).stem}_features.csv"
        graph_dir = root / "outputs" / "trials" / row.study / f"scenario_{row.scenario}" / row.session
        if feature.exists():
            frame = pd.read_csv(feature, dtype=str, keep_default_na=False, low_memory=False)
            frame.columns = frame.columns.str.strip()
            vehicle, vehicle_evidence = _events(frame, "vehicle")
            pedestrian, pedestrian_evidence = _events(frame, "pedestrian")
            status = "processed"
        else:
            frame = pd.DataFrame()
            vehicle = pedestrian = "Unknown"
            vehicle_evidence = pedestrian_evidence = "missing feature file"
            status = "partial"
            failures.append({"StudyFolder": row.study, "ScenarioName": str(row.scenario),
                             "source_file": source, "reason": "missing feature file"})
        signal_internal = str(getattr(row, "driver_signal_result", "unknown"))
        signal = "Unknown" if signal_internal == "unknown" else (
            "No" if signal_internal == "did_not_signal" else "Yes")
        order_map = {
            "pedestrian_first": "Pedestrian", "vehicle_first": "Driver",
            "simultaneous_or_contested": "Both", "not_applicable": "Neither",
            "indeterminate": "Unknown", "": "Unknown",
        }
        arrival, passage = order_map.get(row.arrival_order, "Unknown"), order_map.get(row.passage_order, "Unknown")
        group = gesture_groups.get(source)
        if feature.exists() and group is not None:
            sustained = group[(group.actor == "pedestrian") &
                              (group.gesture_candidate.str.casefold() == "true") &
                              (group.duration_num >= 0.50)]
            gesture = "Yes" if len(sustained) else "No"
        else:
            sustained = pd.DataFrame()
            gesture = "Unknown"
        prediction = {
            "StudyFolder": row.study, "ScenarioName": str(row.scenario),
            "Did the driver signal": signal,
            "How does vehicle speed change?": vehicle,
            "How does pedestrian speed change?": pedestrian,
            "Who has the right of way?（Who reached the intersection first?）": arrival,
            "Who went first？": passage,
            "Did the pedestrian use hand gestures?": gesture,
        }
        predictions.append(prediction)
        audit.append({
            **prediction, "source_file": source, "processed_feature_file": str(feature),
            "graph_directory": str(graph_dir), "driver_signal_internal": signal_internal,
            "vehicle_speed_evidence": vehicle_evidence,
            "pedestrian_speed_evidence": pedestrian_evidence,
            "pedestrian_conflict_entry_time": row.ped_zone_entry_time,
            "vehicle_conflict_entry_time": row.car_zone_entry_time,
            "pedestrian_passage_time": row.ped_conflict_crossing_time,
            "vehicle_passage_time": row.car_conflict_crossing_time,
            "pedestrian_exit_time": row.ped_zone_exit_time,
            "vehicle_exit_time": row.car_zone_exit_time,
            "gesture_event_count": len(sustained), "processing_status": status,
            "data_quality_flags": row.data_quality_flags,
        })
        manifest.append({"StudyFolder": row.study, "ScenarioName": str(row.scenario),
                         "source_file": source, "processed_feature_file": str(feature),
                         "graph_directory": str(graph_dir), "status": status, "reason": ""})
    present = {(item["StudyFolder"], item["ScenarioName"]) for item in predictions}
    discovery = pd.read_csv(root / "outputs" / "summary" / "discovery_manifest.csv",
                            dtype=str, keep_default_na=False)
    discovery = discovery[discovery.scenario.str.casefold() != "practice"]
    for (study, scenario), group in discovery.groupby(["study", "scenario"], sort=False):
        if (study, scenario) in present:
            continue
        source = str(Path(group.iloc[-1].source_file).resolve())
        unknown = {
            "StudyFolder": study, "ScenarioName": scenario,
            "Did the driver signal": "Unknown",
            "How does vehicle speed change?": "Unknown",
            "How does pedestrian speed change?": "Unknown",
            "Who has the right of way?（Who reached the intersection first?）": "Unknown",
            "Who went first？": "Unknown",
            "Did the pedestrian use hand gestures?": "Unknown",
        }
        predictions.append(unknown)
        audit.append({**unknown, "source_file": source, "processed_feature_file": "",
                      "graph_directory": "", "driver_signal_internal": "unknown",
                      "vehicle_speed_evidence": "historical feature processing failed",
                      "pedestrian_speed_evidence": "historical feature processing failed",
                      "processing_status": "failed"})
        manifest.append({"StudyFolder": study, "ScenarioName": scenario, "source_file": source,
                         "processed_feature_file": "", "graph_directory": "",
                         "status": "failed", "reason": "absent from historical trial outcomes"})
        failures.append({"StudyFolder": study, "ScenarioName": scenario,
                         "source_file": source, "reason": "absent from historical trial outcomes"})
    predictions.sort(key=lambda x: natural_key(x["StudyFolder"], x["ScenarioName"]))
    audit.sort(key=lambda x: natural_key(x["StudyFolder"], x["ScenarioName"]))
    pd.DataFrame(predictions, columns=PREDICTION_COLUMNS).to_csv(
        out / "xc_ped_algorithm_predictions.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(audit).to_csv(out / "xc_ped_algorithm_predictions_audit.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(manifest).to_csv(out / "trial_manifest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failures, columns=["StudyFolder", "ScenarioName", "source_file", "reason"]).to_csv(
        out / "failures.csv", index=False, encoding="utf-8-sig")
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, check=True).stdout.strip()
    except Exception:
        commit = "unavailable"
    rules = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_before_generation": commit, "ground_truth_used": False,
        "speed": {"near_stop_mps": 0.15, "slow_acceleration_mps2": -0.25,
                  "vehicle_speed_up_mps2": 0.35, "pedestrian_speed_up_mps2": 0.25,
                  "minimum_duration_sec": 0.50},
        "gesture_minimum_duration_sec": 0.50,
        "arrival_and_passage_tie_sec": 0.10,
        "conflict_occupancy_frames": 3,
        "source_columns": {"vehicle": "A VR Pos X/Z", "pedestrian": "B VR Pos X/Z",
                           "indicator": "A indicators"},
    }
    (out / "classification_rules.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")
    (out / "README.md").write_text(
        "# XC-Ped independent algorithm predictions\n\n"
        "Predictions are generated from existing Xiang feature CSVs and the numerical data behind the graphs. "
        "Ground truth is not read by the exporter. Arrival means conflict-zone boundary arrival, not legal "
        "right-of-way. Passage uses existing conflict-crossing times. Driver hand gestures are excluded.\n\n"
        "Rerun: `python -m pedconflict.xc_ped_export --root .`\n\n"
        "The comparison is a separate evaluation step joined by StudyFolder + ScenarioName.\n",
        encoding="utf-8")
    return {"predictions": len(predictions), "duplicates": duplicate_count,
            "failures": len(failures), "output": str(out)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    print(json.dumps(export_predictions(Path(args.root)), indent=2))


if __name__ == "__main__":
    main()
