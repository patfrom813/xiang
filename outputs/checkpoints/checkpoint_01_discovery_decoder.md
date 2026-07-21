# Checkpoint 01 — Raw discovery and Unity decoder

Status: **complete**  
Scope: raw-file discovery and exactly two decoded trials only. No time reconstruction, feature extraction, conflict analysis, gesture analysis, or graph generation was executed as part of this checkpoint.

## Files changed

- `.gitignore`
- `README.md`
- `config.yaml`
- `requirements.txt`
- `run_pipeline.py`
- `pedconflict/__init__.py`
- `pedconflict/core.py`
- `pedconflict/cli.py`
- `tests/test_checkpoint_01.py`
- `outputs/checkpoints/checkpoint_01_discovery_manifest.csv`
- `outputs/checkpoints/checkpoint_01_decoding_manifest.csv`
- `outputs/checkpoints/checkpoint_01_runtime_seconds.txt`
- `outputs/checkpoints/checkpoint_01_discovery_decoder.md`

Raw CSV files were not modified, renamed, deleted, or overwritten.

## Discovery results

- Raw files discovered: **336**
- Duplicate source paths in manifest: **0**
- Studies: **PedNYC1–PedNYC13 and PedNYC15–PedNYC32**
- PedNYC14: intentionally absent
- Study numbers: `1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32`
- Scenarios: `3, 7, 12, 15, 16, 21, 101, 102, 103, 104, 105, 106`
- Processed/output directories are excluded by path component.
- Manifest fields include absolute and repository-relative source paths, study, study number, scenario, session, byte size, and UTC modification time.

Discovery manifest: `outputs/checkpoints/checkpoint_01_discovery_manifest.csv`

## Two decoded files

| Study | Scenario | Session | Input | Output | Decoded columns | Malformed cells | Runtime |
|---|---:|---|---:|---:|---:|---:|---:|
| PedNYC1 | 3 | `temp_2024-02-22-13-48-59` | 648 × 342 | 648 × 1006 | 332 | 0 | 2.386 s |
| PedNYC2 | 3 | `temp_2024-02-22-16-58-19` | 566 × 342 | 566 × 1006 | 332 | 0 | 1.738 s |

Both outputs are semicolon-delimited and use collision-free source-derived names beneath `data/processed/decoded/<study>/`. Row counts are identical before and after decoding.

Scenario 3 validation passed: the known PedNYC1 file is exactly **648 rows × 342 columns** before decoding and **648 rows × 1006 columns** afterward.

Decoding manifest: `outputs/checkpoints/checkpoint_01_decoding_manifest.csv`

## Tests

Command:

```powershell
$env:PYTHONPATH="$(Resolve-Path '.python_packages');$(Resolve-Path '.')"
python -m pytest tests/test_checkpoint_01.py -q
```

Result: **4 passed in 3.60 seconds**.

Coverage includes filename parsing, duplicate prevention, processed-directory exclusion, semicolon parsing, stray first-header cleanup, float32 vectors, quaternions, modal-length expansion, numeric suffixes, non-base64 pass-through, malformed-cell NaN handling, stable output names, and row preservation.

## Warnings and failures

- Decode failures: **0**
- Malformed encoded cells in the two selected files: **0**
- Decoder warnings: **0**

## Runtime

- Checkpoint execution runtime (discovery plus two decodes and manifest writes): **5.566 seconds**
- Test runtime: **3.60 seconds**

Exact execution command:

```powershell
python run_pipeline.py --overwrite
```

## Recommended Checkpoint 2 command

After the Checkpoint 2 implementation is added, run:

```powershell
python run_pipeline.py checkpoint-02 --manifest outputs/checkpoints/checkpoint_01_decoding_manifest.csv
```
