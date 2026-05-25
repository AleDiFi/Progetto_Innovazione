"""Result summaries, CSV export, and plotting utilities."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import MicrogridParams
from utils import ensure_dir, sanitize_filename

PRESENTATION_DPI = 180


def summarize_results(df: pd.DataFrame, parms: MicrogridParams) -> pd.DataFrame:
    """Compute scenario-level summary metrics."""

    if df.empty:
        raise ValueError("Cannot summarize an empty results DataFrame.")
    comfort_violation = (
        np.maximum(0.0, df["comfort_low"].to_numpy() - df["T_in"].to_numpy())
        + np.maximum(0.0, df["T_in"].to_numpy() - df["comfort_high"].to_numpy())
    )
    summary = {
        "scenario": df["scenario"].iloc[0],
        "total_cost_eur": float(df["step_cost"].sum()),
        "imported_energy_kwh": float((df["P_i"] * parms.dt).sum()),
        "exported_energy_kwh": float((df["P_e"] * parms.dt).sum()),
        "dg_energy_kwh": float((df["P_g"] * parms.dt).sum()),
        "final_bess_soc": float(df["SoC_b"].iloc[-1]),
        "final_hss_soh": float(df["SoH_h"].iloc[-1]),
        "final_pev_soc": float(df["SoC_pev"].iloc[-1]),
        "pev_target": float(parms.SoC_pev_target),
        "pev_target_satisfied": bool(df["SoC_pev"].iloc[-1] + 1e-6 >= parms.SoC_pev_target),
        "comfort_violation_degC_sum": float(comfort_violation.sum()),
        "temp_slack_sum": float((df["slack_temp_low"] + df["slack_temp_high"]).sum()),
        "pev_slack_max_kwh": float(df["slack_pev"].max()),
        "max_power_balance_residual_kw": float(np.abs(df["power_balance_residual"]).max()),
    }
    return pd.DataFrame([summary])


def save_results(df: pd.DataFrame, summary: pd.DataFrame, output_dir: Path, scenario_name: str) -> None:
    """Save results and summary CSV files."""

    output_dir = ensure_dir(output_dir)
    safe = sanitize_filename(scenario_name)
    df.to_csv(output_dir / f"results_{safe}.csv", index=False)
    summary.to_csv(output_dir / f"summary_{safe}.csv", index=False)


def _time_axis(df: pd.DataFrame) -> np.ndarray:
    return np.arange(len(df), dtype=int)


def save_plots(df: pd.DataFrame, summary: pd.DataFrame, output_dir: Path, scenario_name: str) -> None:
    """Generate and save the requested matplotlib plots."""

    output_dir = ensure_dir(output_dir)
    safe = sanitize_filename(scenario_name)
    x = _time_axis(df)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(x, df["P_i"], label="Grid import")
    ax.plot(x, -df["P_e"], label="Grid export")
    ax.plot(x, df["P_pv_used"], label="PV used")
    ax.plot(x, df["P_ul"], label="UPL")
    ax.plot(x, df["P_g"], label="DG")
    ax.plot(x, df["P_fc"], label="Fuel cell")
    ax.plot(x, -df["P_ely"], label="Electrolyzer")
    ax.plot(x, df["P_b_dsc"], label="BESS discharge")
    ax.plot(x, -df["P_b_ch"], label="BESS charge")
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("Power [kW]")
    ax.set_title(f"Power balance components - {scenario_name}")
    ax.grid(True, alpha=0.3)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(output_dir / f"power_balance_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, df["SoC_b"], label="BESS SoC")
    ax.set_ylim(0, 1)
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("SoC [p.u.]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"bess_soc_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, df["SoH_h"], label="HSS SoH", color="tab:green")
    ax.set_ylim(0, 1)
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("SoH [p.u.]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"hss_soh_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(x, df["T_in"], label="Indoor")
    ax.plot(x, df["T_ex"], label="External")
    ax.plot(x, df["T_sp"], label="Setpoint")
    ax.fill_between(x, df["comfort_low"], df["comfort_high"], alpha=0.18, label="Comfort band")
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("Temperature [degC]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"temperature_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.step(x, df["P_c"], where="post", label="Cooling")
    ax.step(x, df["P_h"], where="post", label="Heating")
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("Power [kW]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"hvac_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.step(x, df["P_pev"], where="post", label="PEV power", color="tab:blue")
    ax1.set_xlabel("MPC step [h]")
    ax1.set_ylabel("Power [kW]", color="tab:blue")
    ax2 = ax1.twinx()
    ax2.plot(x, df["SoC_pev"], label="PEV SoC", color="tab:orange")
    ax2.set_ylabel("SoC [p.u.]", color="tab:orange")
    ax2.set_ylim(0, 1)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / f"pev_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(x, df["P_i"], label="Import", color="tab:blue")
    ax1.plot(x, df["P_e"], label="Export", color="tab:cyan")
    ax1.set_xlabel("MPC step [h]")
    ax1.set_ylabel("Grid power [kW]")
    ax2 = ax1.twinx()
    ax2.plot(x, df["c_l"], label="Import price", color="tab:red", linestyle="--")
    ax2.plot(x, df["p_e"], label="Export price", color="tab:green", linestyle="--")
    ax2.set_ylabel("Price [EUR/kWh]")
    ax1.grid(True, alpha=0.3)
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(output_dir / f"grid_prices_{safe}.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, df["step_cost"].cumsum(), label="Cumulative cost")
    ax.set_xlabel("MPC step [h]")
    ax.set_ylabel("Cost [EUR]")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / f"cumulative_cost_{safe}.png", dpi=160)
    plt.close(fig)


def _style_presentation_axis(ax, title: str, xlabel: str | None = None, ylabel: str | None = None) -> None:
    """Apply a common presentation-friendly style to one axis."""

    ax.set_title(title, fontsize=15, weight="bold", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(True, alpha=0.22)
    ax.tick_params(labelsize=9)


def _cost_terms(df: pd.DataFrame, parms: MicrogridParams) -> dict[str, float]:
    """Return objective cost components realized by the first MPC actions."""

    import_cost = float((df["c_l"] * df["P_i"] * parms.dt).sum())
    export_revenue = float((df["p_e"] * df["P_e"] * parms.dt).sum())
    dg_fuel_cost = float((parms.c_f * df["P_g"] * parms.dt / parms.eta_g).sum())
    return {
        "Grid import": import_cost,
        "DG fuel": dg_fuel_cost,
        "Export revenue": -export_revenue,
        "Net total": import_cost + dg_fuel_cost - export_revenue,
    }


def _save_microgrid_architecture(output_dir: Path) -> None:
    """Save a slide explaining the one-bus smart district architecture."""

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    boxes = {
        "PV\nforecast\n+ curtailment": (0.08, 0.72),
        "Grid\nimport/export": (0.08, 0.43),
        "DG\nfuel cost": (0.08, 0.14),
        "BESS\ncharge/discharge\nSoC": (0.42, 0.72),
        "HSS\nElectrolyzer + FC\nSoH": (0.42, 0.14),
        "UPL\nOffice load": (0.74, 0.72),
        "HVAC\ncomfort band": (0.74, 0.43),
        "PEV\navailability + target": (0.74, 0.14),
    }
    bus = plt.Rectangle((0.465, 0.43), 0.07, 0.14, facecolor="#1f77b4", edgecolor="#1f77b4")
    ax.add_patch(bus)
    ax.text(0.5, 0.5, "Electrical\nbus", color="white", ha="center", va="center", fontsize=12, weight="bold")

    for label, (x0, y0) in boxes.items():
        rect = plt.Rectangle((x0, y0), 0.18, 0.14, facecolor="#f7f9fb", edgecolor="#475569", linewidth=1.4)
        ax.add_patch(rect)
        ax.text(x0 + 0.09, y0 + 0.07, label, ha="center", va="center", fontsize=11)
        start = (x0 + 0.18, y0 + 0.07) if x0 < 0.5 else (x0, y0 + 0.07)
        end = (0.465, 0.5) if x0 < 0.5 else (0.535, 0.5)
        ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "lw": 1.5, "color": "#334155"})

    ax.text(0.5, 0.94, "Smart district model architecture", ha="center", va="center", fontsize=20, weight="bold")
    ax.text(
        0.5,
        0.89,
        "The MILP balances supply and demand every hour while respecting storage, comfort, device modes, and PEV charging.",
        ha="center",
        va="center",
        fontsize=12,
        color="#475569",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "00_microgrid_architecture.png", dpi=PRESENTATION_DPI)
    plt.close(fig)


def _save_mpc_workflow(output_dir: Path) -> None:
    """Save a slide explaining the receding-horizon calculation."""

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    steps = [
        ("1. Measure state", "SoC_b, SoH_h,\nT_in, SoC_pev"),
        ("2. Build forecasts", "T_ex, PV, load,\nprices, setpoints"),
        ("3. Solve MILP", "24 h Pyomo model\nwith binary modes"),
        ("4. Apply first action", "Use only j=0\ncontrol values"),
        ("5. Shift horizon", "Update states\nand repeat"),
    ]
    xs = np.linspace(0.08, 0.82, len(steps))
    for i, ((title, body), x0) in enumerate(zip(steps, xs)):
        rect = plt.Rectangle((x0, 0.42), 0.15, 0.22, facecolor="#eef6ff", edgecolor="#2563eb", linewidth=1.5)
        ax.add_patch(rect)
        ax.text(x0 + 0.075, 0.585, title, ha="center", va="center", fontsize=11, weight="bold")
        ax.text(x0 + 0.075, 0.49, body, ha="center", va="center", fontsize=10, color="#334155")
        if i < len(steps) - 1:
            ax.annotate(
                "",
                xy=(x0 + 0.18, 0.53),
                xytext=(x0 + 0.15, 0.53),
                arrowprops={"arrowstyle": "->", "lw": 1.8, "color": "#2563eb"},
            )

    ax.annotate(
        "",
        xy=(0.155, 0.39),
        xytext=(0.895, 0.39),
        arrowprops={"arrowstyle": "->", "lw": 1.8, "color": "#64748b", "connectionstyle": "arc3,rad=-0.22"},
    )
    ax.text(0.5, 0.31, "Closed-loop MPC: the optimization is repeated at every sampling time", ha="center", fontsize=12)
    ax.text(0.5, 0.86, "How the controller computes decisions", ha="center", fontsize=20, weight="bold")
    ax.text(
        0.5,
        0.80,
        "At each hour the model optimizes the next 24 hours, but implements only the first control action.",
        ha="center",
        fontsize=12,
        color="#475569",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "01_mpc_workflow.png", dpi=PRESENTATION_DPI)
    plt.close(fig)


def save_presentation_plots(
    df: pd.DataFrame,
    summary: pd.DataFrame,
    parms: MicrogridParams,
    output_dir: Path,
    scenario_name: str,
) -> None:
    """Save slide-ready plots for one scenario."""

    presentation_dir = ensure_dir(output_dir / "presentation")
    safe = sanitize_filename(scenario_name)
    x = _time_axis(df)
    costs = _cost_terms(df, parms)

    # Dispatch slide: supply and demand shown as stacked areas.
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.33, 7.5), sharex=True)
    supply = [
        df["P_i"].to_numpy(),
        df["P_pv_used"].to_numpy(),
        df["P_b_dsc"].to_numpy(),
        df["P_fc"].to_numpy(),
        df["P_g"].to_numpy(),
    ]
    demand = [
        df["P_ul"].to_numpy(),
        df["P_c"].to_numpy() + df["P_h"].to_numpy(),
        df["P_b_ch"].to_numpy(),
        df["P_ely"].to_numpy(),
        df["P_pev"].to_numpy(),
        df["P_e"].to_numpy(),
    ]
    ax1.stackplot(x, supply, labels=["Grid", "PV used", "BESS dsc", "Fuel cell", "DG"], alpha=0.9)
    ax2.stackplot(x, demand, labels=["Office load", "HVAC", "BESS ch", "Electrolyzer", "PEV", "Export"], alpha=0.9)
    _style_presentation_axis(ax1, "Supply-side dispatch", ylabel="Power [kW]")
    _style_presentation_axis(ax2, "Demand-side allocation", xlabel="Simulation hour", ylabel="Power [kW]")
    ax1.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.25), fontsize=9)
    ax2.legend(ncol=6, loc="upper center", bbox_to_anchor=(0.5, 1.25), fontsize=9)
    fig.suptitle(f"Energy dispatch explained - {scenario_name}", fontsize=19, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(presentation_dir / f"10_dispatch_explained_{safe}.png", dpi=PRESENTATION_DPI)
    plt.close(fig)

    # State and comfort slide.
    fig, axes = plt.subplots(2, 2, figsize=(13.33, 7.5), sharex=True)
    ax = axes[0, 0]
    ax.plot(x, df["SoC_b"], color="#2563eb", label="BESS SoC")
    ax.axhline(parms.SoC_b_min, color="#94a3b8", linestyle="--", linewidth=1)
    ax.axhline(parms.SoC_b_max, color="#94a3b8", linestyle="--", linewidth=1)
    ax.set_ylim(0, 1)
    _style_presentation_axis(ax, "Battery state of charge", ylabel="p.u.")

    ax = axes[0, 1]
    ax.plot(x, df["SoH_h"], color="#16a34a", label="HSS SoH")
    ax.axhline(parms.SoH_min, color="#94a3b8", linestyle="--", linewidth=1)
    ax.axhline(parms.SoH_max, color="#94a3b8", linestyle="--", linewidth=1)
    ax.set_ylim(0, 1)
    _style_presentation_axis(ax, "Hydrogen tank state", ylabel="p.u.")

    ax = axes[1, 0]
    ax.plot(x, df["T_in"], label="Indoor", color="#dc2626")
    ax.plot(x, df["T_ex"], label="External", color="#64748b")
    ax.plot(x, df["T_sp"], label="Setpoint", color="#0f766e")
    ax.fill_between(x, df["comfort_low"], df["comfort_high"], color="#0f766e", alpha=0.12, label="Comfort")
    _style_presentation_axis(ax, "Thermal comfort tracking", xlabel="Simulation hour", ylabel="degC")
    ax.legend(fontsize=8)

    ax = axes[1, 1]
    ax.step(x, df["P_pev"], where="post", color="#7c3aed", label="Charging power")
    ax2 = ax.twinx()
    ax2.plot(x, df["SoC_pev"], color="#f97316", label="PEV SoC")
    ax2.axhline(parms.SoC_pev_target, color="#f97316", linestyle="--", linewidth=1, label="Target")
    ax2.set_ylim(0, 1)
    _style_presentation_axis(ax, "PEV charging target", xlabel="Simulation hour", ylabel="Power [kW]")
    ax2.set_ylabel("SoC [p.u.]")
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], fontsize=8, loc="lower right")
    fig.suptitle(f"Operational constraints and states - {scenario_name}", fontsize=19, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(presentation_dir / f"11_states_constraints_{safe}.png", dpi=PRESENTATION_DPI)
    plt.close(fig)

    # Economics slide.
    fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.5))
    ax = axes[0]
    labels = ["Grid import", "DG fuel", "Export revenue"]
    values = [costs["Grid import"], costs["DG fuel"], costs["Export revenue"]]
    colors = ["#2563eb", "#ef4444", "#22c55e"]
    ax.bar(labels, values, color=colors)
    ax.axhline(0, color="#334155", linewidth=1)
    _style_presentation_axis(ax, "Cost components", ylabel="EUR")
    ax.tick_params(axis="x", rotation=15)

    ax = axes[1]
    ax.plot(x, df["step_cost"].cumsum(), color="#111827", linewidth=2.5, label="Cumulative cost")
    ax2 = ax.twinx()
    ax2.plot(x, df["c_l"], color="#ef4444", linestyle="--", label="Import tariff")
    ax2.plot(x, df["p_e"], color="#22c55e", linestyle="--", label="Export price")
    _style_presentation_axis(ax, "Cost evolution and prices", xlabel="Simulation hour", ylabel="EUR")
    ax2.set_ylabel("EUR/kWh")
    lines = ax.get_lines() + ax2.get_lines()
    ax.legend(lines, [line.get_label() for line in lines], fontsize=9, loc="upper left")
    total = float(summary["total_cost_eur"].iloc[0])
    fig.suptitle(f"Economic result - {scenario_name}: net cost {total:.2f} EUR", fontsize=19, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(presentation_dir / f"12_economics_{safe}.png", dpi=PRESENTATION_DPI)
    plt.close(fig)

    # Compact KPI slide.
    row = summary.iloc[0]
    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    ax.axis("off")
    fig.patch.set_facecolor("white")
    kpis = [
        ("Total cost", f"{row['total_cost_eur']:.0f} EUR"),
        ("Imported energy", f"{row['imported_energy_kwh']:.0f} kWh"),
        ("Exported energy", f"{row['exported_energy_kwh']:.1f} kWh"),
        ("DG energy", f"{row['dg_energy_kwh']:.0f} kWh"),
        ("Final BESS SoC", f"{row['final_bess_soc']:.2f} p.u."),
        ("Final HSS SoH", f"{row['final_hss_soh']:.2f} p.u."),
        ("Comfort violation", f"{row['comfort_violation_degC_sum']:.2g} degC"),
        ("PEV target", "Satisfied" if row["pev_target_satisfied"] else "Not satisfied"),
    ]
    for idx, (label, value) in enumerate(kpis):
        col = idx % 4
        row_idx = idx // 4
        x0 = 0.06 + col * 0.235
        y0 = 0.56 - row_idx * 0.27
        rect = plt.Rectangle((x0, y0), 0.20, 0.18, facecolor="#f8fafc", edgecolor="#cbd5e1", linewidth=1.4)
        ax.add_patch(rect)
        ax.text(x0 + 0.10, y0 + 0.115, value, ha="center", va="center", fontsize=18, weight="bold")
        ax.text(x0 + 0.10, y0 + 0.055, label, ha="center", va="center", fontsize=10, color="#475569")
    ax.text(0.5, 0.86, f"Scenario summary - {scenario_name}", ha="center", fontsize=22, weight="bold")
    ax.text(0.5, 0.80, "Key values produced by the receding-horizon optimization", ha="center", fontsize=12, color="#475569")
    fig.tight_layout()
    fig.savefig(presentation_dir / f"13_kpi_summary_{safe}.png", dpi=PRESENTATION_DPI)
    plt.close(fig)


def save_presentation_overview(
    summaries: pd.DataFrame,
    all_results: dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """Save cross-scenario slide-ready plots and a small index file."""

    presentation_dir = ensure_dir(output_dir / "presentation")
    _save_microgrid_architecture(presentation_dir)
    _save_mpc_workflow(presentation_dir)

    fig, axes = plt.subplots(2, 2, figsize=(13.33, 7.5))
    scenarios = summaries["scenario"].to_list()
    short_labels = [s.replace("scenario_", "").replace("_cf_", "\ncf=") for s in scenarios]
    metrics = [
        ("total_cost_eur", "Total cost [EUR]", "#111827"),
        ("imported_energy_kwh", "Imported energy [kWh]", "#2563eb"),
        ("dg_energy_kwh", "DG energy [kWh]", "#ef4444"),
        ("final_pev_soc", "Final PEV SoC [p.u.]", "#7c3aed"),
    ]
    for ax, (col, title, color) in zip(axes.ravel(), metrics):
        ax.bar(short_labels, summaries[col], color=color, alpha=0.86)
        _style_presentation_axis(ax, title)
        ax.tick_params(axis="x", labelrotation=0)
    fig.suptitle("Scenario comparison", fontsize=20, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(presentation_dir / "02_scenario_comparison.png", dpi=PRESENTATION_DPI)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(13.33, 7.5))
    for scenario, df in all_results.items():
        ax.plot(np.arange(len(df)), df["step_cost"].cumsum(), linewidth=2, label=scenario)
    _style_presentation_axis(ax, "Cumulative cost comparison", xlabel="Simulation hour", ylabel="EUR")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(presentation_dir / "03_cumulative_cost_comparison.png", dpi=PRESENTATION_DPI)
    plt.close(fig)

    index_lines = [
        "# Presentation Figures",
        "",
        "Use these figures as slide-ready material to explain the model, the MPC workflow, and the outputs.",
        "",
        "- `00_microgrid_architecture.png`: system architecture and energy components.",
        "- `01_mpc_workflow.png`: receding-horizon computation process.",
        "- `02_scenario_comparison.png`: cost, import, DG, and PEV comparison across scenarios.",
        "- `03_cumulative_cost_comparison.png`: cumulative cost trajectory across scenarios.",
        "- `10_dispatch_explained_<scenario>.png`: supply and demand dispatch for each scenario.",
        "- `11_states_constraints_<scenario>.png`: storage, comfort, and PEV state constraints.",
        "- `12_economics_<scenario>.png`: cost breakdown and price signals.",
        "- `13_kpi_summary_<scenario>.png`: compact scenario KPIs.",
        "",
    ]
    (presentation_dir / "README_presentation_figures.md").write_text("\n".join(index_lines), encoding="utf-8")
