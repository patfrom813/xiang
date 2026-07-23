from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from pedconflict.ground_truth_export import PREDICTION_COLUMNS


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare locked predictions with XC-Ped ground truth")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output-dir", default="outputs/ground_truth_validation/evaluation")
    args = parser.parse_args()
    predictions = pd.read_csv(args.predictions, dtype=str, keep_default_na=False)
    truth = pd.read_csv(args.ground_truth, dtype=str, keep_default_na=False)
    keys = ["StudyFolder", "ScenarioName"]
    required_truth = set(PREDICTION_COLUMNS)
    if not required_truth.issubset(truth.columns):
        raise ValueError(f"ground truth missing columns: {sorted(required_truth - set(truth.columns))}")
    merged = predictions.merge(truth[PREDICTION_COLUMNS], on=keys, how="outer",
                               suffixes=("_prediction", "_ground_truth"), validate="one_to_one", indicator=True)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    disagreement = merged[merged["_merge"] != "both"].copy()
    for column in PREDICTION_COLUMNS[2:]:
        predicted = merged[f"{column}_prediction"]
        actual = merged[f"{column}_ground_truth"]
        valid = merged["_merge"] == "both"
        report = classification_report(actual[valid], predicted[valid], output_dict=True, zero_division=0)
        labels = sorted(set(actual[valid]) | set(predicted[valid]))
        pd.DataFrame(confusion_matrix(actual[valid], predicted[valid], labels=labels),
                     index=labels, columns=labels).to_csv(output / f"{PREDICTION_COLUMNS.index(column):02d}_confusion_matrix.csv")
        summaries.append({
            "field": column,
            "exact_match_accuracy": float((actual[valid] == predicted[valid]).mean()),
            "unknown_rate": float(predicted[valid].isin(["Unknown", "unavailable"]).mean()),
            "macro_precision": report["macro avg"]["precision"],
            "macro_recall": report["macro avg"]["recall"],
            "macro_f1": report["macro avg"]["f1-score"],
        })
        disagreement = pd.concat([disagreement, merged[valid & (actual != predicted)]])
    pd.DataFrame(summaries).to_csv(output / "field_metrics.csv", index=False)
    disagreement.drop_duplicates().to_csv(output / "disagreements.csv", index=False)
    both = merged["_merge"] == "both"
    complete = np.logical_and.reduce([
        merged.loc[both, f"{column}_prediction"].eq(merged.loc[both, f"{column}_ground_truth"])
        for column in PREDICTION_COLUMNS[2:]
    ])
    (output / "overall.txt").write_text(f"complete_row_agreement={complete.mean():.6f}\n", encoding="utf-8")


if __name__ == "__main__":
    import numpy as np
    main()
