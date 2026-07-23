from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

INDICATOR_PATTERN = re.compile(
    r"^left(?P<left>true|false)_right(?P<right>true|false)$",
    re.IGNORECASE,
)
STATE_LABELS = {
    "did_not_signal": "No signal",
    "signaled_left": "Signaled left",
    "signaled_right": "Signaled right",
    "both_active_or_hazards": "Both active",
    "unknown": "Unknown",
}
STATE_COLORS = {
    "did_not_signal": "#9E9E9E",
    "signaled_left": "#2878B5",
    "signaled_right": "#7B3FB2",
    "both_active_or_hazards": "#C43C39",
    "unknown": "white",
}
RESULT_LABELS = {
    "did_not_signal": "Did not signal",
    "signaled_left": "Signaled left",
    "signaled_right": "Signaled right",
    "both_active_or_hazards": "Both active / possible hazards",
    "unknown": "Unknown",
}


@dataclass(frozen=True)
class IndicatorValue:
    left: bool | None
    right: bool | None
    state: str
    quality: str


@dataclass(frozen=True)
class SignalInterval:
    start: float
    end: float
    true_frames: int


def parse_indicator_value(value: object) -> IndicatorValue:
    """Parse one raw Unity indicator state without treating bad data as no signal."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return IndicatorValue(None, None, "unknown", "missing")
    text = str(value).strip()
    if not text:
        return IndicatorValue(None, None, "unknown", "missing")
    match = INDICATOR_PATTERN.fullmatch(text)
    if not match:
        return IndicatorValue(None, None, "unknown", f"malformed:{text}")
    left = match.group("left").casefold() == "true"
    right = match.group("right").casefold() == "true"
    if left and right:
        state = "both_active_or_hazards"
    elif left:
        state = "signaled_left"
    elif right:
        state = "signaled_right"
    else:
        state = "did_not_signal"
    return IndicatorValue(left, right, state, "valid")


def parse_indicator_series(values: pd.Series) -> pd.DataFrame:
    parsed = [parse_indicator_value(value) for value in values]
    return pd.DataFrame(
        {
            "left_indicator_on": pd.array([item.left for item in parsed], dtype="boolean"),
            "right_indicator_on": pd.array([item.right for item in parsed], dtype="boolean"),
            "indicator_state": [item.state for item in parsed],
            "indicator_data_quality": [item.quality for item in parsed],
        },
        index=values.index,
    )


def find_signal_intervals(
    times: pd.Series | np.ndarray,
    signal: pd.Series | np.ndarray,
    *,
    min_consecutive_frames: int = 2,
    min_duration_sec: float = 0.10,
    blink_gap_tolerance_sec: float = 0.75,
) -> list[SignalInterval]:
    """Find stable on-events and merge short off-gaps caused by lamp blinking."""
    time_values = np.asarray(times, dtype=float)
    raw = pd.array(signal, dtype="boolean")
    valid_true = np.asarray(raw.fillna(False), dtype=bool)
    runs: list[SignalInterval] = []
    start: int | None = None
    for index, is_on in enumerate(valid_true):
        if is_on and start is None:
            start = index
        if start is not None and (not is_on or index == len(valid_true) - 1):
            stop = index if is_on and index == len(valid_true) - 1 else index - 1
            frame_count = stop - start + 1
            duration = max(0.0, time_values[stop] - time_values[start])
            if frame_count >= min_consecutive_frames or duration >= min_duration_sec:
                runs.append(SignalInterval(float(time_values[start]), float(time_values[stop]), frame_count))
            start = None
    merged: list[SignalInterval] = []
    for interval in runs:
        if merged and interval.start - merged[-1].end <= blink_gap_tolerance_sec:
            previous = merged[-1]
            merged[-1] = SignalInterval(
                previous.start,
                interval.end,
                previous.true_frames + interval.true_frames,
            )
        else:
            merged.append(interval)
    return merged


def summarize_trial(
    times: pd.Series,
    parsed: pd.DataFrame,
    *,
    min_consecutive_frames: int = 2,
    min_duration_sec: float = 0.10,
    blink_gap_tolerance_sec: float = 0.75,
) -> tuple[dict, dict[str, list[SignalInterval]]]:
    left_intervals = find_signal_intervals(
        times,
        parsed["left_indicator_on"],
        min_consecutive_frames=min_consecutive_frames,
        min_duration_sec=min_duration_sec,
        blink_gap_tolerance_sec=blink_gap_tolerance_sec,
    )
    right_intervals = find_signal_intervals(
        times,
        parsed["right_indicator_on"],
        min_consecutive_frames=min_consecutive_frames,
        min_duration_sec=min_duration_sec,
        blink_gap_tolerance_sec=blink_gap_tolerance_sec,
    )
    quality_values = sorted(set(parsed.loc[parsed.indicator_data_quality != "valid", "indicator_data_quality"]))
    unknown = bool(quality_values)
    left = bool(left_intervals)
    right = bool(right_intervals)
    both = left and right
    if unknown:
        result = "unknown"
    elif both:
        result = "both_active_or_hazards"
    elif left:
        result = "signaled_left"
    elif right:
        result = "signaled_right"
    else:
        result = "did_not_signal"
    summary = {
        "driver_signaled_left": left,
        "driver_signaled_right": right,
        "driver_indicator_both_active": both,
        "driver_signal_result": result,
        "left_signal_start_time": left_intervals[0].start if left else np.nan,
        "left_signal_end_time": left_intervals[-1].end if left else np.nan,
        "right_signal_start_time": right_intervals[0].start if right else np.nan,
        "right_signal_end_time": right_intervals[-1].end if right else np.nan,
        "indicator_data_quality": "valid" if not unknown else "|".join(quality_values),
    }
    return summary, {"left": left_intervals, "right": right_intervals}


def _state_runs(times: np.ndarray, states: pd.Series) -> list[tuple[float, float, str]]:
    if not len(times):
        return []
    result: list[tuple[float, float, str]] = []
    start = 0
    for index in range(1, len(times) + 1):
        if index == len(times) or states.iloc[index] != states.iloc[start]:
            end = times[index - 1]
            if index < len(times):
                end = (end + times[index]) / 2
            result.append((float(times[start]), float(end), str(states.iloc[start])))
            start = index
    return result


def plot_driver_signal_timeline(
    frame: pd.DataFrame,
    parsed: pd.DataFrame,
    summary: dict,
    output: Path,
) -> None:
    times = pd.to_numeric(frame["ScenarioTime_sec"], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(times)
    times = times[finite]
    view = frame.loc[finite].reset_index(drop=True)
    states = parsed.loc[finite, "indicator_state"].reset_index(drop=True)
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(12, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.1, 1, 1.4]},
        constrained_layout=True,
    )
    ax = axes[0]
    labeled: set[str] = set()
    for start, end, state in _state_runs(times, states):
        kwargs = dict(facecolor=STATE_COLORS[state], edgecolor="#555555", alpha=0.85)
        if state == "unknown":
            kwargs.update(hatch="///", alpha=0.6)
        ax.axvspan(start, end, ymin=0.15, ymax=0.85, **kwargs)
        duration = end - start
        label = STATE_LABELS[state]
        if state != "did_not_signal" and (duration >= 0.45 or state not in labeled):
            ax.text((start + end) / 2, 0.5, label, ha="center", va="center", fontsize=8, color="black")
            labeled.add(state)
    result_label = RESULT_LABELS[summary["driver_signal_result"]]
    fig.suptitle(f"Driver signal result: {result_label}", fontweight="bold", fontsize=14)
    ax.set_ylabel("Indicator state")
    ax.set_yticks([])
    ax.set_ylim(0, 1)
    ax.legend(
        handles=[
            Patch(facecolor=STATE_COLORS[key], edgecolor="#555555", hatch="///" if key == "unknown" else "", label=label)
            for key, label in STATE_LABELS.items()
        ],
        ncol=3,
        loc="upper right",
        fontsize=7.5,
        frameon=False,
    )

    horn = view["A_horn"] if "A_horn" in view else pd.Series(False, index=view.index)
    horn_values = horn.astype(str).str.strip().str.casefold().isin({"true", "1", "1.0"}).astype(int)
    axes[1].step(times, horn_values, where="post", color="#D17A00", linewidth=1.6)
    axes[1].set_ylabel("Horn")
    axes[1].set_yticks([0, 1], ["Not pressed", "Pressed"])
    axes[1].set_ylim(-0.15, 1.15)
    axes[1].grid(axis="x", alpha=0.2)

    steering = pd.to_numeric(view["A_steering"], errors="coerce")
    axes[2].plot(times, steering, color="#2F5D50", linewidth=1.2)
    axes[2].axhline(0, color="#777777", linewidth=0.7)
    axes[2].set_ylabel("Steering input")
    axes[2].set_xlabel("Scenario time (seconds)")
    axes[2].grid(alpha=0.2)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _find_column(frame: pd.DataFrame, needle: str) -> str:
    matches = [column for column in frame.columns if needle in str(column).strip().casefold()]
    if not matches:
        raise KeyError(f"column containing {needle!r} not found")
    return matches[0]


def update_driver_signal_outputs(root: Path, *, pilot_study: str = "PedNYC1") -> dict:
    root = root.resolve()
    outcomes_path = root / "outputs" / "summary" / "trial_outcomes.csv"
    outcomes = pd.read_csv(outcomes_path, dtype=str, keep_default_na=False)
    fields = [
        "driver_signaled_left",
        "driver_signaled_right",
        "driver_indicator_both_active",
        "driver_signal_result",
        "left_signal_start_time",
        "left_signal_end_time",
        "right_signal_start_time",
        "right_signal_end_time",
        "indicator_data_quality",
    ]
    for field in fields:
        if field not in outcomes:
            outcomes[field] = ""
        outcomes[field] = outcomes[field].astype(object)
    if "driver_indicator_code" in outcomes:
        outcomes = outcomes.drop(columns=["driver_indicator_code"])
    if "driver_indicator_used" in outcomes:
        outcomes["driver_indicator_used"] = outcomes["driver_indicator_used"].astype(object)
    unique_values: set[str] = set()
    graph_paths: list[str] = []
    processed = 0
    for index, trial in outcomes.iterrows():
        study, scenario, session = trial["study"], trial["scenario"], trial["session"]
        source_stem = Path(trial["source_file"]).stem
        decoded = root / "data" / "processed" / "decoded" / study / f"{source_stem}_decoded.csv"
        feature = root / "data" / "processed" / "features" / study / f"{source_stem}_features.csv"
        if not decoded.exists() or not feature.exists():
            outcomes.loc[index, "driver_signal_result"] = "unknown"
            outcomes.loc[index, "indicator_data_quality"] = "missing decoded or feature file"
            continue
        decoded_frame = pd.read_csv(decoded, sep=";", dtype=str, keep_default_na=False, low_memory=False)
        feature_frame = pd.read_csv(feature, dtype=str, keep_default_na=False, low_memory=False)
        # Older pilot feature exports retained padding from raw header cells.
        feature_frame.columns = [str(column).strip() for column in feature_frame.columns]
        indicator_column = _find_column(decoded_frame, "indicators")
        raw_values = decoded_frame[indicator_column]
        unique_values.update(value for value in raw_values.unique())
        if len(raw_values) != len(feature_frame):
            outcomes.loc[index, "driver_signal_result"] = "unknown"
            outcomes.loc[index, "indicator_data_quality"] = "decoded/feature row mismatch"
            continue
        parsed = parse_indicator_series(raw_values)
        times = pd.to_numeric(feature_frame["ScenarioTime_sec"], errors="coerce")
        summary, _ = summarize_trial(times, parsed)
        for field, value in summary.items():
            outcomes.loc[index, field] = value
        if "driver_indicator_used" in outcomes:
            outcomes.loc[index, "driver_indicator_used"] = bool(
                summary["driver_signaled_left"] or summary["driver_signaled_right"]
            )
        feature_frame["A_indicators"] = raw_values.to_numpy()
        for column in parsed:
            feature_frame[column] = parsed[column].astype("string").fillna("").to_numpy()
        temporary = feature.with_suffix(".csv.tmp")
        feature_frame.to_csv(temporary, index=False)
        temporary.replace(feature)
        processed += 1
        if study == pilot_study:
            graph = root / "outputs" / "trials" / study / f"scenario_{scenario}" / session / "01_driver_signal_timeline.png"
            plot_driver_signal_timeline(feature_frame, parsed, summary, graph)
            graph_paths.append(str(graph))
    temporary_outcomes = outcomes_path.with_suffix(".csv.tmp")
    outcomes.to_csv(temporary_outcomes, index=False)
    temporary_outcomes.replace(outcomes_path)
    counts = outcomes["driver_signal_result"].value_counts(dropna=False).to_dict()
    return {
        "processed": processed,
        "unique_values": sorted(unique_values),
        "counts": counts,
        "graph_paths": graph_paths,
    }


def regenerate_pilot_graphs(root: Path, *, pilot_study: str = "PedNYC1") -> list[str]:
    root = root.resolve()
    outcomes = pd.read_csv(root / "outputs" / "summary" / "trial_outcomes.csv", dtype=str, keep_default_na=False)
    paths: list[str] = []
    for _, trial in outcomes[outcomes.study == pilot_study].iterrows():
        source_stem = Path(trial["source_file"]).stem
        feature = root / "data" / "processed" / "features" / pilot_study / f"{source_stem}_features.csv"
        frame = pd.read_csv(feature, dtype=str, keep_default_na=False, low_memory=False)
        frame.columns = [str(column).strip() for column in frame.columns]
        parsed = parse_indicator_series(frame["A_indicators"])
        summary, _ = summarize_trial(pd.to_numeric(frame["ScenarioTime_sec"], errors="coerce"), parsed)
        graph = root / "outputs" / "trials" / pilot_study / f"scenario_{trial['scenario']}" / trial["session"] / "01_driver_signal_timeline.png"
        plot_driver_signal_timeline(frame, parsed, summary, graph)
        paths.append(str(graph))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Boolean driver indicators and regenerate driver-signal summaries/plots")
    parser.add_argument("--root", default=".")
    parser.add_argument("--pilot-study", default="PedNYC1")
    parser.add_argument("--graphs-only", action="store_true")
    args = parser.parse_args()
    if args.graphs_only:
        paths = regenerate_pilot_graphs(Path(args.root), pilot_study=args.pilot_study)
        print("regenerated graphs:")
        for path in paths:
            print(f"  {path}")
        return
    result = update_driver_signal_outputs(Path(args.root), pilot_study=args.pilot_study)
    print(f"processed={result['processed']}")
    print("unique raw indicator values:")
    for value in result["unique_values"]:
        print(f"  {value!r}")
    print("trial counts:")
    for key, count in sorted(result["counts"].items()):
        print(f"  {key}: {count}")
    print("regenerated graphs:")
    for path in result["graph_paths"]:
        print(f"  {path}")


if __name__ == "__main__":
    main()
