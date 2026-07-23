from __future__ import annotations

import argparse
import html
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
    truth.columns = [clean(column) for column in truth.columns]
    rename = {column: clean(column) for column in truth.columns}
    truth = truth.rename(columns=rename)
    truth = truth[truth.StudyFolder.map(clean).str.match(r"^PedNYC\d+$")].copy()
    truth["StudyFolder"] = truth.StudyFolder.map(clean)
    truth["ScenarioName"] = truth.ScenarioName.map(clean).str.replace(r"^scenario", "", regex=True, case=False)
    for column in truth.columns:
        truth[column] = truth[column].map(clean)
    merged = pred.merge(truth, on=["StudyFolder", "ScenarioName"], how="outer",
                        suffixes=("_prediction", "_ground_truth"), indicator=True, validate="one_to_one")
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
    comparison.to_csv(output_dir / "xc_ped_prediction_ground_truth_comparison.csv",
                      index=False, encoding="utf-8-sig")
    comparison[comparison.overall_result == "<<< DISCREPANCY >>>"].to_csv(
        output_dir / "xc_ped_discrepancies_only.csv", index=False, encoding="utf-8-sig")
    headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in comparison.columns)
    body = []
    for row in comparison.itertuples(index=False, name=None):
        cells = []
        for value in row:
            style = ' style="background:#ffb3b3;font-weight:bold"' if value == "<<< DISCREPANCY >>>" else ""
            cells.append(f"<td{style}>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    highlighted = (
        "<!doctype html><meta charset='utf-8'><style>table{border-collapse:collapse}"
        "th,td{border:1px solid #bbb;padding:4px;font:12px sans-serif}th{position:sticky;top:0;background:#eee}"
        "</style><table><thead><tr>" + headers + "</tr></thead><tbody>" +
        "".join(body) + "</tbody></table>"
    )
    (output_dir / "xc_ped_prediction_ground_truth_comparison_highlighted.html").write_text(
        highlighted, encoding="utf-8")
    pd.DataFrame(field_stats).to_csv(output_dir / "comparison_summary.csv", index=False)
    summary = {"prediction_rows": len(pred), "ground_truth_rows": len(truth),
               "joined_rows": int((merged._merge == "both").sum()),
               "prediction_only": int((merged._merge == "left_only").sum()),
               "ground_truth_only": int((merged._merge == "right_only").sum()),
               "joined_rows_with_discrepancy": int((mismatch_any & merged._merge.eq("both")).sum())}
    (output_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
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
