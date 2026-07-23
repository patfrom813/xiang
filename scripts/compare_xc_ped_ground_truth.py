from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from pedconflict.xc_ped_export import PREDICTION_COLUMNS


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def compare(prediction_path: Path, ground_truth_path: Path, output_dir: Path) -> dict:
    pred = pd.read_csv(prediction_path, dtype=str, keep_default_na=False)
    truth = pd.read_csv(ground_truth_path, dtype=str, keep_default_na=False)
    pred.columns = [clean(column) for column in pred.columns]
    truth.columns = [clean(column) for column in truth.columns]
    rename = {column: clean(column) for column in truth.columns}
    truth = truth.rename(columns=rename)
    truth = truth[truth.StudyFolder.map(clean).str.match(r"^PedNYC\d+$")].copy()
    truth["StudyFolder"] = truth.StudyFolder.map(clean)
    truth["ScenarioName"] = truth.ScenarioName.map(clean).str.replace(r"^scenario", "", regex=True, case=False)
    pred["StudyFolder"] = pred.StudyFolder.map(clean)
    pred["ScenarioName"] = pred.ScenarioName.map(clean).str.replace(r"^scenario", "", regex=True, case=False)
    for column in pred.columns:
        pred[column] = pred[column].map(clean)
    for column in truth.columns:
        truth[column] = truth[column].map(clean)
    merged = pred.merge(truth, on=["StudyFolder", "ScenarioName"], how="outer",
                        suffixes=("_prediction", "_ground_truth"), indicator=True, validate="one_to_one")
    # The review artifact follows the human ground-truth row scope exactly.
    # Prediction-only trials remain in the independent prediction CSV but do
    # not clutter the visual discrepancy review.
    prediction_only_count = int((merged["_merge"] == "left_only").sum())
    merged = merged[merged["_merge"] != "left_only"].reset_index(drop=True)
    scenario_order = {scenario: position for position, scenario in enumerate(["3", "7", "12", "15", "16", "21"])}
    merged["_study_sort"] = merged["StudyFolder"].str.extract(r"(\d+)", expand=False).astype(int)
    merged["_scenario_sort"] = merged["ScenarioName"].map(scenario_order).fillna(999).astype(int)
    merged = merged.sort_values(
        ["_study_sort", "_scenario_sort", "ScenarioName"], kind="stable"
    ).drop(columns=["_study_sort", "_scenario_sort"]).reset_index(drop=True)
    comparison = merged[["StudyFolder", "ScenarioName", "_merge"]].copy()
    field_stats = []
    mismatch_any = pd.Series(False, index=merged.index)
    for field in PREDICTION_COLUMNS[2:]:
        p, g = f"{field}_prediction", f"{field}_ground_truth"
        comparison[p] = merged[p]
        comparison[g] = merged[g]
        match = merged[p].map(clean).str.casefold() == merged[g].map(clean).str.casefold()
        match &= merged["_merge"].eq("both")
        comparison[f"{field} — result"] = match.map({True: "MATCH", False: "<<< DISCREPANCY >>>"})
        mismatch_any |= ~match
        both = merged["_merge"].eq("both")
        field_stats.append({"field": field, "matched_rows": int(both.sum()),
                            "exact_matches": int((match & both).sum()),
                            "accuracy": float(match[both].mean()) if both.any() else None})
    comparison.insert(3, "overall_result",
                      mismatch_any.map({True: "<<< DISCREPANCY >>>", False: "MATCH"}))
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output_dir / "xc_ped_four_fields_comparison.csv",
                      index=False, encoding="utf-8-sig")
    comparison[comparison.overall_result == "<<< DISCREPANCY >>>"].to_csv(
        output_dir / "xc_ped_four_fields_discrepancies_only.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(field_stats).to_csv(output_dir / "xc_ped_four_fields_summary.csv", index=False)
    summary = {"prediction_rows": len(pred), "ground_truth_rows": len(truth),
               "joined_rows": int((merged._merge == "both").sum()),
               "prediction_only_excluded_from_review": prediction_only_count,
               "ground_truth_only": int((merged._merge == "right_only").sum()),
               "joined_rows_with_discrepancy": int((mismatch_any & merged._merge.eq("both")).sum())}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(compare(Path(args.predictions), Path(args.ground_truth), Path(args.output_dir)), indent=2))


if __name__ == "__main__":
    main()
