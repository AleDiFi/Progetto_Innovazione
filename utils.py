"""Small utilities shared by the MPC project modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def ensure_dir(path: Path) -> Path:
    """Create a directory if needed and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_horizon_slice(array: np.ndarray, k: int, T: int) -> np.ndarray:
    """Return a length-T slice starting at k, wrapping around the year if needed."""

    values = np.asarray(array).reshape(-1)
    if values.size == 0:
        raise ValueError("Cannot slice an empty array.")
    indices = (np.arange(k, k + T) % values.size).astype(int)
    return values[indices].copy()


def clip(values: np.ndarray, lower: float, upper: float) -> np.ndarray:
    """Return values clipped to the inclusive interval [lower, upper]."""

    return np.clip(np.asarray(values, dtype=float), lower, upper)


def pyomo_value(obj: Any, default: float = 0.0) -> float:
    """Safely extract a numeric value from a Pyomo object."""

    try:
        from pyomo.environ import value

        val = value(obj, exception=False)
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def require_length(name: str, values: np.ndarray, expected: int) -> None:
    """Validate that an array has the expected flattened length."""

    actual = np.asarray(values).reshape(-1).size
    if actual != expected:
        raise ValueError(f"{name} must have length {expected}, got {actual}.")


def sanitize_filename(name: str) -> str:
    """Return a filesystem-friendly scenario/file name."""

    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
