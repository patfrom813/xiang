from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

import pandas as pd

from .core import decode_file, decoded_output_path, discover_raw_files


def run_checkpoint_1(root: Path, overwrite: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    started = perf_counter()
    root = root.resolve()
    checkpoint_dir = root / "outputs" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    discovery = discover_raw_files(root)
    discovery.to_csv(checkpoint_dir / "checkpoint_01_discovery_manifest.csv", index=False)

    scenario3 = discovery[(discovery.study == "PedNYC1") & (discovery.scenario == 3)]
    if scenario3.empty:
        raise RuntimeError("Required PedNYC1 Scenario 3 trial was not discovered")
    primary = scenario3.iloc[0]
    alternatives = discovery[
        discovery.study.isin(["PedNYC1", "PedNYC2"])
        & ~((discovery.study == primary.study) & (discovery.scenario == primary.scenario) & (discovery.session == primary.session))
    ].sort_values(["file_size_bytes", "source_relative"], kind="stable")
    if alternatives.empty:
        raise RuntimeError("No second PedNYC1/PedNYC2 trial was discovered")
    selected = pd.DataFrame([primary, alternatives.iloc[0]])

    rows = []
    for trial in selected.itertuples(index=False):
        source = Path(trial.source_file)
        metadata = {"study": trial.study, "scenario": trial.scenario, "session": trial.session}
        output = decoded_output_path(root, metadata, source)
        row = {"source_file": str(source), "output_file": str(output), **metadata}
        try:
            if output.exists() and not overwrite:
                raise FileExistsError(f"Output exists; pass --overwrite to replace this generated decoded file: {output}")
            details = decode_file(source, output)
            warning_text = " | ".join(details.pop("warnings"))
            details.pop("decoded_columns")
            rows.append({**row, **details, "status": "ok", "warnings": warning_text, "error_message": ""})
        except Exception as error:
            rows.append({**row, "status": "failed", "warnings": "", "error_message": f"{type(error).__name__}: {error}", "runtime_seconds": 0.0})
    decoding = pd.DataFrame(rows)
    decoding.to_csv(checkpoint_dir / "checkpoint_01_decoding_manifest.csv", index=False)
    (checkpoint_dir / "checkpoint_01_runtime_seconds.txt").write_text(f"{perf_counter() - started:.6f}\n", encoding="utf-8")
    return discovery, decoding


def main() -> None:
    parser = argparse.ArgumentParser(description="Checkpoint 1: discover raw PedNYC trials and decode exactly two files")
    parser.add_argument("--root", default=".")
    parser.add_argument("--overwrite", action="store_true", help="replace only the two selected generated outputs")
    args = parser.parse_args()
    discovery, decoding = run_checkpoint_1(Path(args.root), args.overwrite)
    print(f"Discovered {len(discovery)} raw files; decoded {int((decoding.status == 'ok').sum())}/2 selected files.")


if __name__ == "__main__":
    main()
