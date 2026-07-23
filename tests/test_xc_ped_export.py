import numpy as np
import pandas as pd

from pedconflict.xc_ped_export import PREDICTION_COLUMNS, _events, natural_key


def test_natural_sort():
    assert natural_key("PedNYC2", "101") < natural_key("PedNYC15", "3")


def test_speed_slow_then_fast():
    accel = np.r_[[-0.5] * 8, [0] * 3, [0.5] * 8]
    frame = pd.DataFrame({
        "ScenarioTime_sec": np.arange(len(accel)) * 0.1,
        "car_speed_xz_smooth": np.maximum(0, 1 + np.cumsum(accel) * 0.1),
        "car_accel_xz": accel,
    })
    assert _events(frame, "vehicle")[0] == "Slowing down then Speeding up"


def test_required_schema_excludes_driver_gesture():
    assert len(PREDICTION_COLUMNS) == 8
    assert all("driver use hand gestures" not in value.casefold() for value in PREDICTION_COLUMNS)
