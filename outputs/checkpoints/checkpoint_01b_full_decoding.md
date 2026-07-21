# Checkpoint 01B — Full decoding batch

Status: **complete with one recorded source-file failure**

Scope: discovery, decoding, resume validation, and manifests only. No later pipeline stage was executed.

## Results

- Authoritative raw-file count: **336**
- Approximate expected count: **417**
- Difference: **−81 files**
- Files attempted: **336**
- Valid decoded outputs: **335**
- Newly decoded during the final resume run: **0**
- Skipped after validation because a valid output already existed: **335**
- Failed: **1**
- Successful input rows: **315,895**
- Successful output rows: **315,895**
- Row preservation: **confirmed for all 335 successful outputs**
- Unique output paths: confirmed

The discovery manifest was authoritative. It contains PedNYC1–PedNYC13 and PedNYC15–PedNYC32; PedNYC14 is absent as intended.

## Commands

```powershell
# Dry run
python run_checkpoint_01b.py --dry-run --resume --workers 1

# Required five-file batch
python run_checkpoint_01b.py --limit 5 --resume --workers 1

# Full batch and exact resume command
python run_checkpoint_01b.py --resume --workers 1
```

The five-file batch passed semicolon readability, row preservation, and dimension validation for all five outputs. The manifest is updated after every file, progress is printed for every source, one worker is enforced, and interruption leaves resumable manifests.

## Failure

- Source: `PedNYC6/csv/CSV_Scenario-Ped-15_Session-temp_2024-03-01-11-48-06.csv`
- Reason: physical CSV row 4113 has **329 fields**; the header requires **342 fields**.
- The raw file was not changed or repaired.
- The failure manifest contains the complete traceback.

## Malformed-cell accounting

- Checkpoint 1A's two decoded files recorded **0 malformed encoded cells**.
- The 335 valid outputs pre-existed from earlier interrupted work and were resume-validated rather than decoded again. Their historical cell-warning counters were unavailable, so their malformed counts are blank with an explicit warning rather than invented as zero.
- The failed source did not reach cell-level decoding because its semicolon record structure was invalid.

## Scenario 3 validation

- PedNYC1 Scenario 3 input: **648 rows × 342 columns**
- Output: **648 rows × 1006 columns**
- Status: `skipped_valid` after complete readability and dimension validation
- Exact row preservation: confirmed

These dimensions were not imposed on other files.

## Runtime and tests

- Full batch runtime: **119.256 seconds**
- Average per attempted file: **0.345 seconds**
- Maximum per file: **1.240 seconds**
- Workers: **1**
- Tests: **5 passed** (`python -m pytest tests/test_checkpoint_01.py -q`)

## Output locations

- Discovery: `outputs/checkpoints/checkpoint_01_discovery_manifest.csv`
- Decoding: `outputs/checkpoints/checkpoint_01b_decoding_manifest.csv`
- Failures: `outputs/checkpoints/checkpoint_01b_failure_manifest.csv`
- Metadata: `outputs/checkpoints/checkpoint_01b_run_metadata.json`
- Decoded CSVs: `data/processed/decoded/<study>/<source-derived-filename>_decoded.csv`
- Report: `outputs/checkpoints/checkpoint_01b_full_decoding.md`

## Files added or changed

- `.gitignore`
- `pedconflict/batch.py`
- `run_checkpoint_01b.py`
- `tests/test_checkpoint_01.py`
- `outputs/checkpoints/checkpoint_01_discovery_manifest.csv`
- `outputs/checkpoints/checkpoint_01b_decoding_manifest.csv`
- `outputs/checkpoints/checkpoint_01b_failure_manifest.csv`
- `outputs/checkpoints/checkpoint_01b_run_metadata.json`
- `outputs/checkpoints/checkpoint_01b_full_decoding.md`

No raw CSV was modified, renamed, deleted, or overwritten.
