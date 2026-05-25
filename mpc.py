"""Receding-horizon MPC simulation loop."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import MicrogridParams
from model import build_microgrid_model, extract_first_action, solve_model
from utils import get_horizon_slice


def _select_pv_profile(parms: MicrogridParams, data: dict, forecast: bool = True) -> np.ndarray:
    """Select the configured PV source."""

    suffix = "forecast" if forecast else "actual"
    if parms.pv_source == "irradiance":
        return data[f"P_pv_irr_{suffix}"]
    return data[f"P_pv_{suffix}"]


def _build_horizon_data(parms: MicrogridParams, data: dict, k: int) -> dict:
    """Collect all forecast data for one MPC horizon."""

    T = int(parms.T)
    ur_pev = get_horizon_slice(data["UR_pev"], k, T)
    if ur_pev[0] >= 0.5:
        first_unavailable = np.where(ur_pev < 0.5)[0]
        pev_deadline_step = int(first_unavailable[0]) if first_unavailable.size else T
    else:
        pev_deadline_step = T

    return {
        "T_ex": get_horizon_slice(data["T_ex_forecast"], k, T),
        "P_pv": get_horizon_slice(_select_pv_profile(parms, data, forecast=True), k, T),
        "P_ul": get_horizon_slice(data["P_ul_forecast"], k, T),
        "c_l": get_horizon_slice(data["c_l"], k, T),
        "p_e": get_horizon_slice(data["p_e"], k, T),
        "T_sp": get_horizon_slice(data["T_sp"], k, T),
        "UR_pev": ur_pev,
        "PEV_deadline_step": pev_deadline_step,
    }


def run_mpc(
    parms: MicrogridParams,
    data: dict,
    start_index: int,
    n_steps: int,
    scenario_name: str,
) -> pd.DataFrame:
    """Run a receding-horizon MPC simulation and return a results DataFrame."""

    initial_state = {
        "SoC_b": parms.SoC_b_0,
        "SoH_h": parms.SoH_h_0,
        "T_in": float(data["T_sp"][start_index % len(data["T_sp"])]),
        "SoC_pev": parms.SoC_pev_0,
        "SoC_pev_target": parms.SoC_pev_target,
    }
    rows: list[dict] = []

    for step, k in enumerate(range(start_index, start_index + n_steps)):
        idx = k % len(data["index"])
        horizon_data = _build_horizon_data(parms, data, k)
        model = build_microgrid_model(parms, horizon_data, initial_state)
        model._parms = parms
        solve_model(model)
        action = extract_first_action(model)

        # Use actual/measured exogenous variables for simulation bookkeeping.
        P_pv_actual = float(_select_pv_profile(parms, data, forecast=False)[idx])
        P_ul_actual = float(data["P_ul_actual"][idx])
        T_ex_actual = float(data["T_ex_actual"][idx])
        c_l = float(data["c_l"][idx])
        p_e = float(data["p_e"][idx])
        T_sp = float(data["T_sp"][idx])

        step_cost = (
            c_l * action["P_i"] * parms.dt
            - p_e * action["P_e"] * parms.dt
            + parms.c_f * action["P_g"] * parms.dt / parms.eta_g
        )
        power_balance_residual = (
            action["P_i"]
            + (float(horizon_data["P_pv"][0]) - action["P_curt"])
            + action["P_b_dsc"]
            + action["P_fc"]
            + action["P_g"]
            - action["P_e"]
            - float(horizon_data["P_ul"][0])
            - action["P_c"]
            - action["P_h"]
            - action["P_b_ch"]
            - action["P_ely"]
            - action["P_pev"]
        )

        SoC_pev_next = min(
            1.0,
            initial_state["SoC_pev"] + parms.dt / parms.E_pev * parms.eta_pev * action["P_pev"],
        )

        row = {
            "scenario": scenario_name,
            "step": step,
            "time_index": idx,
            "timestamp": data["index"][idx],
            "P_i": action["P_i"],
            "P_e": action["P_e"],
            "P_pv": float(horizon_data["P_pv"][0]),
            "P_pv_actual": P_pv_actual,
            "P_pv_used": max(0.0, float(horizon_data["P_pv"][0]) - action["P_curt"]),
            "P_curt": action["P_curt"],
            "P_ul": float(horizon_data["P_ul"][0]),
            "P_ul_actual": P_ul_actual,
            "P_b_ch": action["P_b_ch"],
            "P_b_dsc": action["P_b_dsc"],
            "P_fc": action["P_fc"],
            "P_ely": action["P_ely"],
            "P_g": action["P_g"],
            "P_c": action["P_c"],
            "P_h": action["P_h"],
            "P_pev": action["P_pev"],
            "SoC_b": action["SoC_b_next"],
            "SoH_h": action["SoH_h_next"],
            "T_in": action["T_in_next"],
            "T_ex": T_ex_actual,
            "T_ex_forecast": float(horizon_data["T_ex"][0]),
            "T_sp": T_sp,
            "comfort_low": T_sp - parms.Delta_T,
            "comfort_high": T_sp + parms.Delta_T,
            "SoC_pev": SoC_pev_next,
            "UR_pev": float(horizon_data["UR_pev"][0]),
            "c_l": c_l,
            "p_e": p_e,
            "step_cost": step_cost,
            "objective": action["objective"],
            "power_balance_residual": power_balance_residual,
            "slack_pev": action["slack_pev"],
            "slack_temp_low": action["slack_temp_low_next"],
            "slack_temp_high": action["slack_temp_high_next"],
        }
        for key, value in action.items():
            if key.startswith("delta_"):
                row[key] = value
        rows.append(row)

        initial_state["SoC_b"] = action["SoC_b_next"]
        initial_state["SoH_h"] = action["SoH_h_next"]
        initial_state["T_in"] = action["T_in_next"]
        initial_state["SoC_pev"] = SoC_pev_next

    return pd.DataFrame(rows)
