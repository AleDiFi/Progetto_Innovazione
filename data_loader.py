"""Dataset loading and exogenous-profile construction."""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from config import MicrogridParams
from utils import clip, get_horizon_slice


def _load_mat_variable(path: Path, variable: str) -> np.ndarray:
    """Load one variable from a MATLAB v5 .mat file."""

    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")
    mat = sio.loadmat(path)
    if variable not in mat:
        visible = sorted(k for k in mat if not k.startswith("__"))
        raise KeyError(f"{path.name} does not contain {variable!r}. Found: {visible}")
    return np.asarray(mat[variable], dtype=float)


def _column(matrix: np.ndarray, index: int, name: str) -> np.ndarray:
    """Extract and flatten a column from a 2-D matrix."""

    arr = np.asarray(matrix, dtype=float)
    if arr.ndim == 1:
        if index != 0:
            raise ValueError(f"{name} is 1-D, cannot extract column {index}.")
        return arr.reshape(-1)
    if arr.shape[1] <= index:
        raise ValueError(f"{name} has shape {arr.shape}, cannot extract column {index}.")
    return arr[:, index].reshape(-1)


def _scale_to_nominal(values: np.ndarray, nominal: float, name: str) -> np.ndarray:
    """Scale a nonnegative profile so its maximum is the selected nominal value."""

    arr = np.asarray(values, dtype=float).reshape(-1)
    max_value = float(np.nanmax(arr))
    if max_value <= 0:
        raise ValueError(f"{name} cannot be scaled because its maximum is {max_value}.")
    scaled = arr / max_value * nominal
    return np.maximum(scaled, 0.0)


def build_synthetic_2022_index(n_hours: int = 8760) -> pd.DatetimeIndex:
    """Return a non-leap hourly calendar used for tariff and seasonal profiles."""

    return pd.date_range("2022-01-01 00:00:00", periods=n_hours, freq="h")


def build_import_price_profile(
    index_or_datetime: pd.DatetimeIndex,
    F1: float = 0.53276,
    F2: float = 0.54858,
    F3: float = 0.46868,
) -> np.ndarray:
    """Build the F1/F2/F3 import tariff profile in EUR/kWh.

    Approximation used when no official holiday calendar is supplied:
    F1 is Monday-Friday 08:00-19:00; F2 is Monday-Friday 07:00-08:00 and
    19:00-23:00 plus Saturday 07:00-23:00; F3 is nights, Sundays, holidays,
    and all remaining hours. Italian public holidays are approximated by fixed
    2022 dates for this one-year dataset.
    """

    index = pd.DatetimeIndex(index_or_datetime)
    prices = np.full(len(index), F3, dtype=float)
    holidays = {
        pd.Timestamp("2022-01-01").date(),
        pd.Timestamp("2022-01-06").date(),
        pd.Timestamp("2022-04-18").date(),
        pd.Timestamp("2022-04-25").date(),
        pd.Timestamp("2022-05-01").date(),
        pd.Timestamp("2022-06-02").date(),
        pd.Timestamp("2022-08-15").date(),
        pd.Timestamp("2022-11-01").date(),
        pd.Timestamp("2022-12-08").date(),
        pd.Timestamp("2022-12-25").date(),
        pd.Timestamp("2022-12-26").date(),
    }

    for pos, ts in enumerate(index):
        hour = ts.hour
        weekday = ts.weekday()  # Monday=0, Sunday=6
        is_holiday = ts.date() in holidays
        if is_holiday or weekday == 6:
            prices[pos] = F3
        elif weekday <= 4 and 8 <= hour < 19:
            prices[pos] = F1
        elif (weekday <= 4 and ((7 <= hour < 8) or (19 <= hour < 23))) or (
            weekday == 5 and 7 <= hour < 23
        ):
            prices[pos] = F2
        else:
            prices[pos] = F3
    return prices


def build_temperature_setpoint(index: pd.DatetimeIndex) -> np.ndarray:
    """Return 22 degC from April to September and 20 degC otherwise."""

    months = pd.DatetimeIndex(index).month
    return np.where((months >= 4) & (months <= 9), 22.0, 20.0).astype(float)


def build_pev_availability(index: pd.DatetimeIndex, params: MicrogridParams) -> np.ndarray:
    """Return a binary PEV connection profile.

    Default assumption: the vehicle is connected during the evening/night window
    from 18:00 to 08:00. The start/end hours are configurable in config.py.
    """

    hours = pd.DatetimeIndex(index).hour
    start = params.pev_connected_start_hour
    end = params.pev_connected_end_hour
    if start == end:
        available = np.ones(len(index), dtype=int)
    elif start < end:
        available = ((hours >= start) & (hours < end)).astype(int)
    else:
        available = ((hours >= start) | (hours < end)).astype(int)
    return available


def load_project_data(data_dir: Path, use_forecast: bool = True) -> dict:
    """Load project datasets and construct year-long exogenous arrays.

    Parameters
    ----------
    data_dir:
        Folder containing the MATLAB datasets.
    use_forecast:
        Select forecast columns where a single profile is requested. Both
        forecast and actual arrays are still returned for MPC/simulation use.
    """

    params = MicrogridParams()
    data_dir = Path(data_dir)
    T_ex_mat = _load_mat_variable(data_dir / "T_ex_rome_campus_bio_medico_2022.mat", "T_ex")
    Ir_mat = _load_mat_variable(data_dir / "Ir_rome_campus_bio_medico_2022.mat", "Ir")
    office_mat = _load_mat_variable(data_dir / "office_load.mat", "Pul")
    pun_mat = _load_mat_variable(data_dir / "PUN_2022.mat", "pun")
    res_mat = sio.loadmat(data_dir / "res_1_year_pu.mat")
    if "P_pv" not in res_mat:
        raise KeyError("res_1_year_pu.mat does not contain 'P_pv'.")
    P_pv_pu_mat = np.asarray(res_mat["P_pv"], dtype=float)

    index = build_synthetic_2022_index(8760)

    T_ex_forecast = _column(T_ex_mat, 1, "T_ex")
    T_ex_actual = _column(T_ex_mat, 2, "T_ex")
    Ir_forecast = _column(Ir_mat, 1, "Ir")
    Ir_actual = _column(Ir_mat, 2, "Ir")
    P_ul_forecast = _scale_to_nominal(_column(office_mat, 1, "office_load/Pul"), params.P_ul_nom, "office load")
    P_ul_actual = _scale_to_nominal(_column(office_mat, 2, "office_load/Pul"), params.P_ul_nom, "office load actual")

    pun = np.asarray(pun_mat, dtype=float).reshape(-1) / 1000.0
    if np.nanmax(pun) > 2.0:
        warnings.warn("PUN appears unusually high after EUR/MWh to EUR/kWh conversion.", RuntimeWarning)

    P_pv_pu_forecast = clip(_column(P_pv_pu_mat, 0, "P_pv"), 0.0, 1.0)
    P_pv_pu_actual = clip(_column(P_pv_pu_mat, 1, "P_pv"), 0.0, 1.0)
    P_pv_forecast = P_pv_pu_forecast * params.P_pv_nom
    P_pv_actual = P_pv_pu_actual * params.P_pv_nom

    Ir_norm_forecast = clip(Ir_forecast / max(float(np.nanmax(Ir_forecast)), 1000.0), 0.0, 1.0)
    Ir_norm_actual = clip(Ir_actual / max(float(np.nanmax(Ir_actual)), 1000.0), 0.0, 1.0)
    P_pv_irr_forecast = Ir_norm_forecast * params.P_pv_nom
    P_pv_irr_actual = Ir_norm_actual * params.P_pv_nom

    arrays = {
        "T_ex": T_ex_forecast if use_forecast else T_ex_actual,
        "T_ex_forecast": T_ex_forecast,
        "T_ex_actual": T_ex_actual,
        "Ir_forecast": Ir_forecast,
        "Ir_actual": Ir_actual,
        "P_pv": P_pv_forecast if use_forecast else P_pv_actual,
        "P_pv_forecast": P_pv_forecast,
        "P_pv_actual": P_pv_actual,
        "P_pv_irr_forecast": P_pv_irr_forecast,
        "P_pv_irr_actual": P_pv_irr_actual,
        "P_ul": P_ul_forecast if use_forecast else P_ul_actual,
        "P_ul_forecast": P_ul_forecast,
        "P_ul_actual": P_ul_actual,
        "p_e": pun,
        "c_l": build_import_price_profile(index, params.F1, params.F2, params.F3),
        "T_sp": build_temperature_setpoint(index),
        "UR_pev": build_pev_availability(index, params),
        "index": index,
    }

    expected = 8760
    for key in ["T_ex_forecast", "T_ex_actual", "P_ul_forecast", "P_ul_actual", "P_pv_forecast", "p_e"]:
        if len(arrays[key]) != expected:
            raise ValueError(f"{key} must have length {expected}, got {len(arrays[key])}.")
    if np.any(arrays["P_ul_forecast"] < 0) or np.any(arrays["P_pv_forecast"] < 0):
        raise ValueError("Scaled load and PV profiles must be nonnegative.")
    if np.nanmax(arrays["P_pv_forecast"]) > params.P_pv_nom + 1e-6:
        raise ValueError("PV profile exceeds nominal power after clipping.")

    return arrays


__all__ = [
    "build_import_price_profile",
    "build_pev_availability",
    "build_synthetic_2022_index",
    "build_temperature_setpoint",
    "get_horizon_slice",
    "load_project_data",
]
