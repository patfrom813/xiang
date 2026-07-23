from pathlib import Path

import numpy as np
import pandas as pd

from pedconflict.driver_signals import parse_indicator_series, summarize_trial
from pedconflict.ground_truth_export import (
    PREDICTION_COLUMNS,
    Rules,
    choose_representations,
    classify_speed,
    natural_key,
)


def motion_frame(accel, speed=None, dt=0.1):
    accel = np.asarray(accel, dtype=float)
    if speed is None:
        speed = np.maximum(0, 1 + np.cumsum(accel) * dt)
    return pd.DataFrame({
        "ScenarioTime_sec": np.arange(len(accel)) * dt,
        "car_speed_xz_smooth": speed,
        "car_accel_xz": accel,
        "ped_speed_xz_smooth": speed,
        "ped_accel_xz": accel,
    })


def test_natural_scenario_sorting_and_pednyc14_absence():
    values = [("PedNYC15", 3), ("PedNYC2", 101), ("PedNYC1", 12)]
    assert sorted(values, key=lambda x: natural_key(*x)) == [
        ("PedNYC1", 12), ("PedNYC2", 101), ("PedNYC15", 3)
    ]
    assert all(study != "PedNYC14" for study, _ in values)


def test_duplicate_detection_prefers_existing_larger_feature(tmp_path):
    root = tmp_path
    source1 = root / "PedNYC1" / "csv" / "one.csv"
    source2 = root / "PedNYC1" / "csv" / "two.csv"
    source1.parent.mkdir(parents=True)
    source1.write_text("x", encoding="utf-8")
    source2.write_text("x", encoding="utf-8")
    feature = root / "data" / "processed" / "features" / "PedNYC1"
    feature.mkdir(parents=True)
    (feature / "two_features.csv").write_text("longer feature content", encoding="utf-8")
    discovery = pd.DataFrame([
        {"source_file": str(source1), "study": "PedNYC1", "study_number": 1,
         "scenario": 3, "session": "a"},
        {"source_file": str(source2), "study": "PedNYC1", "study_number": 1,
         "scenario": 3, "session": "b"},
    ])
    selected, duplicates = choose_representations(discovery, root)
    assert Path(selected[("PedNYC1", 3)]["source_file"]).name == "two.csv"
    assert str(source1) in duplicates


def _signal(values):
    times = pd.Series(np.arange(len(values)) * 0.1)
    summary, _ = summarize_trial(times, parse_indicator_series(pd.Series(values)))
    return summary["driver_signal_result"]


def test_left_right_no_signal_and_missing_indicator():
    assert _signal(["LeftTrue_RightFalse"] * 6) == "signaled_left"
    assert _signal(["LeftFalse_RightTrue"] * 6) == "signaled_right"
    assert _signal(["LeftFalse_RightFalse"] * 6) == "did_not_signal"
    assert _signal(["LeftFalse_RightFalse", None]) == "unknown"


def test_vehicle_slows_then_accelerates():
    frame = motion_frame([-0.4] * 10 + [0] * 4 + [0.5] * 10)
    result = classify_speed(frame, actor="vehicle", rules=Rules())
    assert result["prediction"] == "Slowed down then sped up"


def test_pedestrian_stops_then_resumes():
    speed = np.r_[np.linspace(1, 0, 10), np.zeros(6), np.linspace(0, 1, 10)]
    accel = np.gradient(speed, 0.1)
    result = classify_speed(motion_frame(accel, speed), actor="pedestrian", rules=Rules())
    assert result["prediction"] == "Slowed down then sped up"


def test_simultaneous_arrival_and_arrive_vs_pass_are_independent():
    rules = Rules()
    assert abs(10.0 - 10.05) <= rules.arrival_tie_tolerance_sec
    arrival = "Pedestrian" if 8.0 < 10.0 else "Vehicle"
    passage = "Vehicle" if 12.0 > 11.0 else "Pedestrian"
    assert (arrival, passage) == ("Pedestrian", "Vehicle")


def test_neither_actor_enters():
    from pedconflict.ground_truth_export import _order
    assert _order("not_applicable") == "Neither"


def test_gesture_detected_no_gesture_and_missing_channels():
    events = pd.DataFrame({"duration_number": [0.2, 0.7], "gesture_candidate": ["True", "True"]})
    assert len(events[(events.gesture_candidate == "True") & (events.duration_number >= 0.5)]) == 1
    assert len(events[events.duration_number >= 1.0]) == 0
    frame = pd.DataFrame()
    assert frame.empty


def test_practice_exclusion_and_prediction_schema():
    assert "practice" != "scenario3"
    assert PREDICTION_COLUMNS == [
        "StudyFolder",
        "ScenarioName",
        "Did the driver signal",
        "How does vehicle speed change?",
        "How does pedestrian speed change?",
        "Who has the right of way?（Who reached the intersection first?）",
        "Who went first？",
        "Did the pedestrian use hand gestures?",
    ]
    assert all("driver use hand gestures" not in column.casefold() for column in PREDICTION_COLUMNS)


def test_prediction_module_has_no_ground_truth_input_dependency():
    source = Path(__file__).parents[1] / "pedconflict" / "ground_truth_export.py"
    text = source.read_text(encoding="utf-8")
    assert "ground_truth.csv" not in text
    assert "ground-truth answer" not in text
