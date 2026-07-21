import base64
import struct
from pathlib import Path

import numpy as np
import pandas as pd

from pedconflict.core import decode_dataframe, decode_file, discover_raw_files, parse_raw_path
from pedconflict.batch import csv_dimensions, validate_pair


def encoded(*values):
    return base64.b64encode(struct.pack("<" + "f" * len(values), *values)).decode()


def test_filename_parsing():
    result = parse_raw_path(Path("PedNYC15/csv/CSV_Scenario-Ped-101_Session-temp_2024-01-02-03-04-05.csv"))
    assert result == {"study": "PedNYC15", "study_number": 15, "scenario": 101, "session": "temp_2024-01-02-03-04-05"}


def test_discovery_excludes_processed_and_prevents_duplicates(tmp_path):
    raw = tmp_path / "PedNYC1" / "csv" / "CSV_Scenario-Ped-3_Session-temp_a.csv"
    processed = tmp_path / "data" / "processed" / "PedNYC1" / "CSV_Scenario-Ped-7_Session-temp_b.csv"
    raw.parent.mkdir(parents=True); processed.parent.mkdir(parents=True)
    raw.write_text("a;b\n1;2\n"); processed.write_text("a;b\n1;2\n")
    manifest = discover_raw_files(tmp_path)
    assert len(manifest) == 1
    assert manifest.source_file.is_unique
    assert manifest.iloc[0].scenario == 3


def test_decoder_vector_quaternion_modal_malformed_passthrough_and_names():
    frame = pd.DataFrame({
        "]GameTime": ["1", "2", "3"],
        "vector": [encoded(1, 2, 3), encoded(4, 5, 6), "malformed"],
        "quaternion": [encoded(0, 0, 0, 1)] * 3,
        "other": [encoded(1, 2), encoded(3, 4), encoded(5, 6, 7)],
        "plain": ["alpha", "beta", "gamma"],
    })
    decoded, details = decode_dataframe(frame)
    assert list(decoded.columns) == ["GameTime", "vector X", "vector Y", "vector Z", "quaternion X", "quaternion Y", "quaternion Z", "quaternion W", "other 0", "other 1", "plain"]
    assert len(decoded) == len(frame)
    assert np.isnan(decoded.loc[2, "vector X"])
    assert np.isnan(decoded.loc[2, "other 0"])
    assert details["malformed_cell_count"] == 2


def test_semicolon_file_round_trip_and_no_row_loss(tmp_path):
    source = tmp_path / "source.csv"; output = tmp_path / "decoded.csv"
    source.write_text("]id;position;plain\n1;" + encoded(1, 2, 3) + ";a\n2;" + encoded(4, 5, 6) + ";b\n", encoding="utf-8")
    details = decode_file(source, output)
    decoded = pd.read_csv(output, sep=";")
    assert details["input_rows"] == details["output_rows"] == 2
    assert list(decoded.columns) == ["id", "position X", "position Y", "position Z", "plain"]


def test_batch_validation_rejects_row_loss(tmp_path):
    source = tmp_path / "source.csv"; output = tmp_path / "output.csv"
    source.write_text("a;b\n1;2\n3;4\n", encoding="utf-8")
    output.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    assert csv_dimensions(source) == (2, 2)
    try:
        validate_pair(source, output)
    except ValueError as error:
        assert "row mismatch" in str(error)
    else:
        raise AssertionError("row loss was not rejected")
