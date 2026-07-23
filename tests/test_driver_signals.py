import numpy as np
import pandas as pd

from pedconflict.driver_signals import (
    find_signal_intervals,
    parse_indicator_series,
    parse_indicator_value,
    summarize_trial,
)


def test_no_signal_mapping():
    value = parse_indicator_value("LeftFalse_RightFalse")
    assert (value.left, value.right, value.state, value.quality) == (False, False, "did_not_signal", "valid")


def test_left_mapping():
    value = parse_indicator_value("LeftTrue_RightFalse")
    assert (value.left, value.right, value.state) == (True, False, "signaled_left")


def test_right_mapping():
    value = parse_indicator_value("LeftFalse_RightTrue")
    assert (value.left, value.right, value.state) == (False, True, "signaled_right")


def test_both_mapping():
    value = parse_indicator_value("LeftTrue_RightTrue")
    assert (value.left, value.right, value.state) == (True, True, "both_active_or_hazards")


def test_whitespace_and_case_are_tolerated():
    value = parse_indicator_value("  LEFTtrue_RIGHTfalse  ")
    assert value.state == "signaled_left"


def test_missing_is_unknown():
    assert parse_indicator_value(None).state == "unknown"
    assert parse_indicator_value(np.nan).quality == "missing"
    assert parse_indicator_value(" ").state == "unknown"


def test_malformed_is_unknown():
    value = parse_indicator_value("indicator code 0")
    assert value.state == "unknown"
    assert value.quality.startswith("malformed:")


def test_one_frame_noise_is_rejected():
    intervals = find_signal_intervals([0, 0.1, 0.2], [False, True, False])
    assert intervals == []


def test_blink_gaps_merge_and_multiple_events_remain_distinct():
    times = np.arange(12) * 0.1
    signal = [False, True, True, False, True, True, False, False, False, True, True, False]
    intervals = find_signal_intervals(times, signal, blink_gap_tolerance_sec=0.25)
    assert len(intervals) == 2
    assert intervals[0].start == 0.1 and intervals[0].end == 0.5
    assert intervals[1].start == 0.9 and intervals[1].end == 1.0


def test_multiple_left_and_right_intervals_produce_both_trial_result():
    raw = pd.Series(
        ["LeftFalse_RightFalse", "LeftTrue_RightFalse", "LeftTrue_RightFalse",
         "LeftFalse_RightFalse", "LeftFalse_RightTrue", "LeftFalse_RightTrue"]
    )
    parsed = parse_indicator_series(raw)
    summary, events = summarize_trial(pd.Series(np.arange(6) * 0.2), parsed, blink_gap_tolerance_sec=0.1)
    assert len(events["left"]) == len(events["right"]) == 1
    assert summary["driver_indicator_both_active"] is True
    assert summary["driver_signal_result"] == "both_active_or_hazards"


def test_constant_no_signal_trial():
    parsed = parse_indicator_series(pd.Series(["LeftFalse_RightFalse"] * 10))
    summary, events = summarize_trial(pd.Series(np.arange(10) * 0.1), parsed)
    assert not events["left"] and not events["right"]
    assert summary["driver_signal_result"] == "did_not_signal"


def test_any_bad_frame_makes_trial_unknown():
    parsed = parse_indicator_series(pd.Series(["LeftFalse_RightFalse", "bad"]))
    summary, _ = summarize_trial(pd.Series([0.0, 0.1]), parsed)
    assert summary["driver_signal_result"] == "unknown"
    assert "malformed" in summary["indicator_data_quality"]
