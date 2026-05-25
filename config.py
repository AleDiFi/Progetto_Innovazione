"""Configuration for the smart district MILP-MPC project.

All powers are in kW, energies in kWh, prices in EUR/kWh, temperatures in degC,
and state of charge/state of hydrogen values are in per-unit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class MicrogridParams:
    """Numerical parameters for the MILP-MPC smart district model."""

    # General MPC settings
    T: int = 24
    dt: float = 1.0

    # Paths
    data_dir: Path = Path("Datasets for project")
    output_dir: Path = Path("outputs")

    # Grid
    P_i_max: float = 330.0
    P_e_max: float = 160.0

    # PV and uncontrollable load
    P_pv_nom: float = 185.0
    P_ul_nom: float = 450.0
    pv_source: str = "pu"  # "pu" uses res_1_year_pu.mat; "irradiance" uses Ir.

    # BESS
    P_b_nom: float = 140.0
    E_b: float = 140.0
    eta_b_ch: float = 0.95
    eta_b_dsc: float = 0.90
    SoC_b_min: float = 0.10
    SoC_b_max: float = 0.90
    SoC_b_0: float = 0.50
    k_sd: float = 0.0

    # Hydrogen Storage System: energy-equivalent model.
    P_fc_nom: float = 65.0
    P_fc_min: float = 6.5
    eta_fc: float = 0.62
    P_ely_nom: float = 65.0
    # Some course slides show 65 kW, equal to nominal. The exam prompt and a
    # practical technical-minimum interpretation use 6.5 kW; keep configurable.
    P_ely_min: float = 6.5
    eta_ely: float = 0.70
    E_h: float = 10.0
    SoH_min: float = 0.10
    SoH_max: float = 0.90
    SoH_h_0: float = 0.50

    # Non-renewable distributed generator
    P_g_nom: float = 120.0
    P_g_min: float = 40.0
    eta_g: float = 0.75
    c_f: float = 0.15

    # HVAC thermal load
    P_hvac_nom: float = 12.0
    R: float = 1.9
    eta_c: float = 1.90
    eta_h: float = 0.85
    C: float = 3.925
    Delta_T: float = 2.0

    # PEV
    P_pev_nom: float = 10.0
    eta_pev: float = 0.90
    E_pev: float = 30.0
    SoC_pev_0: float = 0.30
    SoC_pev_target: float = 0.80
    pev_connected_start_hour: int = 18
    pev_connected_end_hour: int = 8

    # Prices and objective penalties
    F1: float = 0.53276
    F2: float = 0.54858
    F3: float = 0.46868
    slack_pev_penalty: float = 1.0e5
    slack_temp_penalty: float = 1.0e5
    epsilon_regularization: float = 1.0e-6

    # Solver settings
    solver_fallbacks: tuple[str, ...] = ("gurobi", "appsi_highs", "highs", "cbc", "glpk")
    solver_time_limit_s: float | None = None
    tee: bool = False


@dataclass(frozen=True)
class Scenario:
    """A simulation scenario for the MPC loop."""

    name: str
    start_index: int
    n_steps: int
    c_f: float
    season: str


def default_params(**overrides: object) -> MicrogridParams:
    """Return default parameters, optionally overriding selected fields."""

    params = MicrogridParams()
    if overrides:
        params = replace(params, **overrides)
    return params


def default_scenarios(n_steps: int = 48) -> list[Scenario]:
    """Return the four required fuel-price/season scenarios.

    A synthetic 2022 non-leap hourly calendar is used by the data loader. January
    15 and July 15 at 00:00 are fixed, reproducible winter/summer days.
    """

    winter_start = 14 * 24
    summer_start = (31 + 28 + 31 + 30 + 31 + 30 + 14) * 24
    return [
        Scenario("scenario_A_summer_cf_0_15", summer_start, n_steps, 0.15, "summer"),
        Scenario("scenario_B_summer_cf_0_45", summer_start, n_steps, 0.45, "summer"),
        Scenario("scenario_C_winter_cf_0_15", winter_start, n_steps, 0.15, "winter"),
        Scenario("scenario_D_winter_cf_0_45", winter_start, n_steps, 0.45, "winter"),
    ]


def to_namespace(params: MicrogridParams) -> SimpleNamespace:
    """Convert dataclass parameters to a mutable SimpleNamespace if desired."""

    return SimpleNamespace(**params.__dict__)
