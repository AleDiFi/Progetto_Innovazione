"""Pyomo MILP model for one smart district MPC optimization step."""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import numpy as np
from pyomo.environ import (Binary, ConcreteModel, Constraint, NonNegativeReals,
                           Objective, RangeSet, Reals, SolverFactory,
                           SolverStatus, TerminationCondition, Var, minimize,
                           value)

from utils import ensure_dir, require_length


def _horizon_value(horizon_data: dict, name: str, j: int) -> float:
    """Return scalar horizon data as a plain float."""

    return float(np.asarray(horizon_data[name], dtype=float).reshape(-1)[j])


def _validate_horizon(parms, horizon_data: dict) -> None:
    """Validate that all exogenous arrays required by the model are length T."""

    required = ("T_ex", "P_pv", "P_ul", "c_l", "p_e", "T_sp", "UR_pev")
    missing = [key for key in required if key not in horizon_data]
    if missing:
        raise KeyError(f"Missing horizon data keys: {missing}")
    for key in required:
        require_length(key, np.asarray(horizon_data[key]), int(parms.T))


def build_microgrid_model(parms, horizon_data: dict, initial_state: dict) -> ConcreteModel:
    """Build and return one Pyomo ConcreteModel for the MPC horizon.

    The model is a linear MILP. Dynamic states are indexed over K=0..T, while
    control actions and binary operating modes are indexed over J=0..T-1.
    """

    _validate_horizon(parms, horizon_data)
    T = int(parms.T)
    dt = float(parms.dt)
    alpha = math.exp(-dt / (float(parms.C) * float(parms.R)))
    beta = 1.0 - alpha

    model = ConcreteModel(name="smart_district_mpc")
    model.J = RangeSet(0, T - 1)
    model.K = RangeSet(0, T)

    # Grid and PV variables.
    model.P_i = Var(model.J, domain=NonNegativeReals)
    model.P_e = Var(model.J, domain=NonNegativeReals)
    model.P_curt = Var(model.J, domain=NonNegativeReals)

    # BESS variables.
    model.P_b_ch = Var(model.J, domain=NonNegativeReals)
    model.P_b_dsc = Var(model.J, domain=NonNegativeReals)
    model.SoC_b = Var(model.K, domain=Reals, bounds=(parms.SoC_b_min, parms.SoC_b_max))

    # Hydrogen Storage System variables.
    model.P_fc = Var(model.J, domain=NonNegativeReals)
    model.P_ely = Var(model.J, domain=NonNegativeReals)
    model.SoH_h = Var(model.K, domain=Reals, bounds=(parms.SoH_min, parms.SoH_max))

    # Non-renewable generator.
    model.P_g = Var(model.J, domain=NonNegativeReals)

    # HVAC variables.
    model.P_c = Var(model.J, domain=NonNegativeReals)
    model.P_h = Var(model.J, domain=NonNegativeReals)
    model.T_in = Var(model.K, domain=Reals)
    model.slack_temp_low = Var(model.K, domain=NonNegativeReals)
    model.slack_temp_high = Var(model.K, domain=NonNegativeReals)

    # PEV variables.
    model.P_pev = Var(model.J, domain=NonNegativeReals)
    model.slack_pev = Var(domain=NonNegativeReals)

    # Binary mode variables.
    model.delta_i = Var(model.J, domain=Binary)
    model.delta_e = Var(model.J, domain=Binary)
    model.delta_b_ch = Var(model.J, domain=Binary)
    model.delta_b_dsc = Var(model.J, domain=Binary)
    model.delta_fc = Var(model.J, domain=Binary)
    model.delta_ely = Var(model.J, domain=Binary)
    model.delta_g = Var(model.J, domain=Binary)
    model.delta_c = Var(model.J, domain=Binary)
    model.delta_h = Var(model.J, domain=Binary)

    # Initial measured states are fixed by equality constraints.
    model.init_soc_b = Constraint(expr=model.SoC_b[0] == float(initial_state["SoC_b"]))
    model.init_soh_h = Constraint(expr=model.SoH_h[0] == float(initial_state["SoH_h"]))
    model.init_t_in = Constraint(expr=model.T_in[0] == float(initial_state["T_in"]))
    model.init_temp_slack_low = Constraint(expr=model.slack_temp_low[0] == 0.0)
    model.init_temp_slack_high = Constraint(expr=model.slack_temp_high[0] == 0.0)

    def grid_import_limit_rule(m, j):
        return m.P_i[j] <= parms.P_i_max * m.delta_i[j]

    def grid_export_limit_rule(m, j):
        return m.P_e[j] <= parms.P_e_max * m.delta_e[j]

    def grid_mode_rule(m, j):
        return m.delta_i[j] + m.delta_e[j] <= 1

    model.grid_import_limit = Constraint(model.J, rule=grid_import_limit_rule)
    model.grid_export_limit = Constraint(model.J, rule=grid_export_limit_rule)
    model.grid_mode = Constraint(model.J, rule=grid_mode_rule)

    def pv_curtailment_rule(m, j):
        return m.P_curt[j] <= _horizon_value(horizon_data, "P_pv", j)

    model.pv_curtailment = Constraint(model.J, rule=pv_curtailment_rule)

    def power_balance_rule(m, j):
        pv_used = _horizon_value(horizon_data, "P_pv", j) - m.P_curt[j]
        supply = m.P_i[j] + pv_used + m.P_b_dsc[j] + m.P_fc[j] + m.P_g[j]
        demand = (
            m.P_e[j]
            + _horizon_value(horizon_data, "P_ul", j)
            + m.P_c[j]
            + m.P_h[j]
            + m.P_b_ch[j]
            + m.P_ely[j]
            + m.P_pev[j]
        )
        return supply == demand

    model.power_balance = Constraint(model.J, rule=power_balance_rule)

    def bess_dynamics_rule(m, j):
        return m.SoC_b[j + 1] == (
            m.SoC_b[j]
            + dt / parms.E_b * (parms.eta_b_ch * m.P_b_ch[j] - (1.0 / parms.eta_b_dsc) * m.P_b_dsc[j])
            - dt / 24.0 * parms.k_sd
        )

    def bess_charge_limit_rule(m, j):
        return m.P_b_ch[j] <= parms.P_b_nom * m.delta_b_ch[j]

    def bess_discharge_limit_rule(m, j):
        return m.P_b_dsc[j] <= parms.P_b_nom * m.delta_b_dsc[j]

    def bess_mode_rule(m, j):
        return m.delta_b_ch[j] + m.delta_b_dsc[j] <= 1

    model.bess_dynamics = Constraint(model.J, rule=bess_dynamics_rule)
    model.bess_charge_limit = Constraint(model.J, rule=bess_charge_limit_rule)
    model.bess_discharge_limit = Constraint(model.J, rule=bess_discharge_limit_rule)
    model.bess_mode = Constraint(model.J, rule=bess_mode_rule)

    def hss_dynamics_rule(m, j):
        return m.SoH_h[j + 1] == (
            m.SoH_h[j]
            + dt / parms.E_h * (parms.eta_ely * m.P_ely[j] - (1.0 / parms.eta_fc) * m.P_fc[j])
        )

    def fc_min_rule(m, j):
        return m.P_fc[j] >= parms.P_fc_min * m.delta_fc[j]

    def fc_max_rule(m, j):
        return m.P_fc[j] <= parms.P_fc_nom * m.delta_fc[j]

    def ely_min_rule(m, j):
        return m.P_ely[j] >= parms.P_ely_min * m.delta_ely[j]

    def ely_max_rule(m, j):
        return m.P_ely[j] <= parms.P_ely_nom * m.delta_ely[j]

    def hss_mode_rule(m, j):
        return m.delta_fc[j] + m.delta_ely[j] <= 1

    model.hss_dynamics = Constraint(model.J, rule=hss_dynamics_rule)
    model.fc_min = Constraint(model.J, rule=fc_min_rule)
    model.fc_max = Constraint(model.J, rule=fc_max_rule)
    model.ely_min = Constraint(model.J, rule=ely_min_rule)
    model.ely_max = Constraint(model.J, rule=ely_max_rule)
    model.hss_mode = Constraint(model.J, rule=hss_mode_rule)

    def dg_min_rule(m, j):
        return m.P_g[j] >= parms.P_g_min * m.delta_g[j]

    def dg_max_rule(m, j):
        return m.P_g[j] <= parms.P_g_nom * m.delta_g[j]

    model.dg_min = Constraint(model.J, rule=dg_min_rule)
    model.dg_max = Constraint(model.J, rule=dg_max_rule)

    def hvac_dynamics_rule(m, j):
        return m.T_in[j + 1] == (
            alpha * m.T_in[j]
            - beta * parms.R * (parms.eta_c * m.P_c[j] - parms.eta_h * m.P_h[j])
            + beta * _horizon_value(horizon_data, "T_ex", j)
        )

    def cooling_limit_rule(m, j):
        return m.P_c[j] <= parms.P_hvac_nom * m.delta_c[j]

    def heating_limit_rule(m, j):
        return m.P_h[j] <= parms.P_hvac_nom * m.delta_h[j]

    def hvac_mode_rule(m, j):
        return m.delta_c[j] + m.delta_h[j] <= 1

    def comfort_low_rule(m, j):
        return m.T_in[j + 1] >= _horizon_value(horizon_data, "T_sp", j) - parms.Delta_T - m.slack_temp_low[j + 1]

    def comfort_high_rule(m, j):
        return m.T_in[j + 1] <= _horizon_value(horizon_data, "T_sp", j) + parms.Delta_T + m.slack_temp_high[j + 1]

    model.hvac_dynamics = Constraint(model.J, rule=hvac_dynamics_rule)
    model.cooling_limit = Constraint(model.J, rule=cooling_limit_rule)
    model.heating_limit = Constraint(model.J, rule=heating_limit_rule)
    model.hvac_mode = Constraint(model.J, rule=hvac_mode_rule)
    model.comfort_low = Constraint(model.J, rule=comfort_low_rule)
    model.comfort_high = Constraint(model.J, rule=comfort_high_rule)

    def pev_power_rule(m, j):
        return m.P_pev[j] <= _horizon_value(horizon_data, "UR_pev", j) * parms.P_pev_nom

    model.pev_power = Constraint(model.J, rule=pev_power_rule)

    required_pev_energy = max(
        0.0,
        parms.E_pev * (float(initial_state["SoC_pev_target"]) - float(initial_state["SoC_pev"])),
    )
    # If the PEV is connected now, require the remaining energy before the next
    # disconnection. This prevents receding-horizon procrastination where every
    # solve schedules charging later, but the applied first action never charges.
    pev_deadline_step = int(horizon_data.get("PEV_deadline_step", T))
    pev_deadline_step = max(1, min(T, pev_deadline_step))
    pev_requirement_indices = range(pev_deadline_step) if _horizon_value(horizon_data, "UR_pev", 0) >= 0.5 else model.J
    model.pev_energy_requirement = Constraint(
        expr=dt * sum(parms.eta_pev * model.P_pev[j] for j in pev_requirement_indices)
        + model.slack_pev
        >= required_pev_energy
    )

    def objective_rule(m):
        operating_cost = sum(
            _horizon_value(horizon_data, "c_l", j) * m.P_i[j] * dt
            - _horizon_value(horizon_data, "p_e", j) * m.P_e[j] * dt
            + parms.c_f * m.P_g[j] * dt / parms.eta_g
            for j in m.J
        )
        slack_cost = parms.slack_pev_penalty * m.slack_pev + parms.slack_temp_penalty * sum(
            m.slack_temp_low[k] + m.slack_temp_high[k] for k in m.K
        )
        regularization = parms.epsilon_regularization * sum(
            m.P_curt[j] + m.P_b_ch[j] + m.P_b_dsc[j] + m.P_fc[j] + m.P_ely[j] for j in m.J
        )
        return operating_cost + slack_cost + regularization

    model.obj = Objective(rule=objective_rule, sense=minimize)
    model._parms = parms
    model._horizon_data = horizon_data
    model._initial_state = initial_state
    return model


def _candidate_solvers(solver_name: str | None, fallbacks: tuple[str, ...]) -> list[str]:
    if solver_name:
        return [solver_name]
    return list(fallbacks)


def _solver_is_available(name: str) -> bool:
    """Check Pyomo solver availability without raising on missing executables."""

    try:
        solver = SolverFactory(name)
        return bool(solver.available(exception_flag=False))
    except Exception:
        return False


def solve_model(model, solver_name: str | None = None):
    """Solve a Pyomo model using Gurobi, HiGHS, CBC, or GLPK fallback order."""

    parms = getattr(model, "_parms", None)
    fallbacks = getattr(parms, "solver_fallbacks", ("gurobi", "appsi_highs", "highs", "cbc", "glpk"))
    tee = bool(getattr(parms, "tee", False))
    candidates = _candidate_solvers(solver_name, tuple(fallbacks))
    unavailable: list[str] = []

    for name in candidates:
        if not _solver_is_available(name):
            unavailable.append(name)
            continue
        solver = SolverFactory(name)
        time_limit = getattr(parms, "solver_time_limit_s", None)
        if time_limit is not None:
            try:
                if name == "gurobi":
                    solver.options["TimeLimit"] = float(time_limit)
                elif name in {"cbc", "glpk", "highs", "appsi_highs"}:
                    solver.options["time_limit"] = float(time_limit)
            except Exception:
                warnings.warn(f"Could not set time limit for solver {name}.", RuntimeWarning)
        results = solver.solve(model, tee=tee)
        status = results.solver.status
        termination = results.solver.termination_condition
        if status == SolverStatus.ok and termination in {
            TerminationCondition.optimal,
            TerminationCondition.feasible,
        }:
            model._solver_name = name
            model._solver_results = results
            return results

        if termination == TerminationCondition.infeasible:
            output_dir = ensure_dir(Path(getattr(parms, "output_dir", "outputs")))
            model.write(str(output_dir / "infeasible_model.lp"), io_options={"symbolic_solver_labels": True})
        raise RuntimeError(f"Solver {name} failed with status={status}, termination={termination}.")

    raise RuntimeError(
        "No available MILP solver found. Tried: "
        + ", ".join(candidates)
        + ". Install gurobi, highspy, CBC, or GLPK and retry."
    )


def extract_first_action(model) -> dict:
    """Extract the first MPC control action and next controlled states."""

    return {
        "P_i": value(model.P_i[0]),
        "P_e": value(model.P_e[0]),
        "P_curt": value(model.P_curt[0]),
        "P_b_ch": value(model.P_b_ch[0]),
        "P_b_dsc": value(model.P_b_dsc[0]),
        "P_fc": value(model.P_fc[0]),
        "P_ely": value(model.P_ely[0]),
        "P_g": value(model.P_g[0]),
        "P_c": value(model.P_c[0]),
        "P_h": value(model.P_h[0]),
        "P_pev": value(model.P_pev[0]),
        "delta_i": value(model.delta_i[0]),
        "delta_e": value(model.delta_e[0]),
        "delta_b_ch": value(model.delta_b_ch[0]),
        "delta_b_dsc": value(model.delta_b_dsc[0]),
        "delta_fc": value(model.delta_fc[0]),
        "delta_ely": value(model.delta_ely[0]),
        "delta_g": value(model.delta_g[0]),
        "delta_c": value(model.delta_c[0]),
        "delta_h": value(model.delta_h[0]),
        "SoC_b_next": value(model.SoC_b[1]),
        "SoH_h_next": value(model.SoH_h[1]),
        "T_in_next": value(model.T_in[1]),
        "slack_pev": value(model.slack_pev),
        "slack_temp_low_next": value(model.slack_temp_low[1]),
        "slack_temp_high_next": value(model.slack_temp_high[1]),
        "objective": value(model.obj),
    }
