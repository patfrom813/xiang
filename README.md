# PedNYC deterministic pipeline

This repository currently implements **Checkpoint 1 only**: deterministic raw-file discovery and Unity base64 float-array decoding. It intentionally does not reconstruct time, calculate features, analyze conflicts or gestures, or generate graphs.

## Setup

```powershell
python -m pip install -r requirements.txt
```

## Run Checkpoint 1

The command discovers every raw trial but decodes exactly two files: PedNYC1 Scenario 3 and the smallest other trial in PedNYC1/PedNYC2. Existing decoded outputs are protected unless `--overwrite` is explicit.

```powershell
python run_pipeline.py --overwrite
```

Outputs are written beneath `outputs/checkpoints/`; decoded files use `data/processed/decoded/<study>/<source-derived-name>_decoded.csv`. Raw files are opened read-only and never modified.

## Test

```powershell
python -m pytest -q
```

Checkpoint 2 recommended command (after its implementation):

```powershell
python run_pipeline.py checkpoint-02 --manifest outputs/checkpoints/checkpoint_01_decoding_manifest.csv
```
