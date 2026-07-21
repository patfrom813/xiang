# PedNYC deterministic pipeline

This repository currently implements **Checkpoint 1 only**: deterministic raw-file discovery and Unity base64 float-array decoding. It intentionally does not reconstruct time, calculate features, analyze conflicts or gestures, or generate graphs.

## Setup

```powershell
python -m pip install -r requirements.txt
```

## Run Checkpoint 1

The full decoder discovers all 374 raw trials, writes semicolon-delimited decoded files under `data/processed/decoded/<study>/`, and resumes only after validating existing outputs.

```powershell
python run_checkpoint_01b.py --dry-run --workers 2
python run_checkpoint_01b.py --limit 5 --resume --workers 2
python run_checkpoint_01b.py --resume --workers 2
```

Manifests are written under `outputs/summary/`, and the full report is `outputs/checkpoints/checkpoint_01_full_decoding.md`. Decoded filenames retain scenario and session identity. Raw files are opened read-only and never modified.

## Test

```powershell
python -m pytest -q
```

Checkpoint 2 recommended command (after its implementation):

```powershell
python run_pipeline.py checkpoint-02 --manifest outputs/checkpoints/checkpoint_01_decoding_manifest.csv
```
