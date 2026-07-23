# XC-Ped independent algorithm predictions

Predictions are generated from existing Xiang feature CSVs and the numerical data behind the graphs. Ground truth is not read by the exporter. Arrival means conflict-zone boundary arrival, not legal right-of-way. Passage uses existing conflict-crossing times. Driver hand gestures are excluded.

Rerun: `python -m pedconflict.xc_ped_export --root .`

The comparison is a separate evaluation step joined by StudyFolder + ScenarioName.
