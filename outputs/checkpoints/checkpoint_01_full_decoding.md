# Checkpoint 01: Full CSV decoding

- Absolute repository path: `C:\Users\patl5\OneDrive\Documents\BURE\xiang`
- Absolute decoded-output directory: `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded`
- Expected raw count: 374
- Actual raw count discovered: 374
- Files attempted or resume-validated: 374
- Files freshly decoded this run: 0
- Files successfully decoded this run: 0
- Files skipped (valid existing): 374
- Files failed: 0
- Valid decoded files on disk: 374
- Total input rows: 472388
- Total decoded rows: 472388
- Row preservation: confirmed
- Total input columns (per-file sum): 127908
- Total output columns (per-file sum): 376244
- Total malformed cells recorded: 3334
- Warnings from files freshly decoded this run: 0 (legacy skipped entries do not retain a separate warning count)
- Total runtime: 177.541 seconds
- Average runtime per attempted/resume-validated file: 0.475 seconds
- Maximum recorded file runtime: 3.438 seconds
- Decoded directory size: 8793191317 bytes

## Per-study discovery and decoded counts

| Study | Expected | Discovered | Decoded |
|---|---:|---:|---:|
| PedNYC1 | 13 | 13 | 13 |
| PedNYC2 | 13 | 13 | 13 |
| PedNYC3 | 13 | 13 | 13 |
| PedNYC4 | 14 | 14 | 14 |
| PedNYC5 | 13 | 13 | 13 |
| PedNYC6 | 12 | 12 | 12 |
| PedNYC7 | 18 | 18 | 18 |
| PedNYC8 | 13 | 13 | 13 |
| PedNYC9 | 15 | 15 | 15 |
| PedNYC10 | 10 | 10 | 10 |
| PedNYC11 | 13 | 13 | 13 |
| PedNYC12 | 13 | 13 | 13 |
| PedNYC13 | 13 | 13 | 13 |
| PedNYC15 | 8 | 8 | 8 |
| PedNYC16 | 15 | 15 | 15 |
| PedNYC17 | 13 | 13 | 13 |
| PedNYC18 | 8 | 8 | 8 |
| PedNYC19 | 13 | 13 | 13 |
| PedNYC20 | 10 | 10 | 10 |
| PedNYC21 | 9 | 9 | 9 |
| PedNYC22 | 13 | 13 | 13 |
| PedNYC23 | 13 | 13 | 13 |
| PedNYC24 | 14 | 14 | 14 |
| PedNYC25 | 12 | 12 | 12 |
| PedNYC26 | 13 | 13 | 13 |
| PedNYC27 | 4 | 4 | 4 |
| PedNYC28 | 13 | 13 | 13 |
| PedNYC29 | 14 | 14 | 14 |
| PedNYC30 | 11 | 11 | 11 |
| PedNYC31 | 5 | 5 | 5 |
| PedNYC32 | 13 | 13 | 13 |

## Discovery discrepancies

- None.

## PedNYC1 Scenario 3 validation

- 648 x 342 input; 648 x 1006 output; `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-3_Session-temp_2024-02-22-13-48-59_decoded.csv`

## Failures

- None.

## Commands executed

- `python -m pytest -q`
- `python run_checkpoint_01b.py --dry-run --workers 2`
- `python run_checkpoint_01b.py --limit 5 --resume --workers 2`
- `python run_checkpoint_01b.py --resume --workers 2`

Exact resume command: `python run_checkpoint_01b.py --resume --workers 2`

## Automated tests

- 12 passed in 3.11s

## Representative decoded outputs

- `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-101_Session-temp_2024-02-22-13-58-23_decoded.csv`
- `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-102_Session-temp_2024-02-22-14-03-29_decoded.csv`
- `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-103_Session-temp_2024-02-22-14-05-41_decoded.csv`
- `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-104_Session-temp_2024-02-22-14-01-04_decoded.csv`
- `C:\Users\patl5\OneDrive\Documents\BURE\xiang\data\processed\decoded\PedNYC1\CSV_Scenario-Ped-105_Session-temp_2024-02-22-14-07-56_decoded.csv`

## Manifests

- `outputs/summary/discovery_manifest.csv`
- `outputs/summary/decoding_manifest.csv`
- `outputs/summary/decoding_failures.csv`
- `outputs/summary/decoding_run_metadata.json`

## Files added or changed

- `pedconflict/core.py`
- `pedconflict/batch.py`
- `tests/test_checkpoint_01.py`
- `README.md`
- `outputs/summary/*`
- `outputs/checkpoints/checkpoint_01_full_decoding.md`
