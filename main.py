"""Entry point for the smart district MILP-MPC project."""

from __future__ import annotations

import warnings
from dataclasses import replace

import pandas as pd

from config import default_params, default_scenarios
from data_loader import load_project_data
from mpc import run_mpc
from results import (save_plots, save_presentation_overview,
                     save_presentation_plots, save_results, summarize_results)
from utils import ensure_dir


def _print_summary(summary: pd.DataFrame) -> None:
    row = summary.iloc[0]
    print(f"\n[{row['scenario']}]")
    print(f"  Total cost:              {row['total_cost_eur']:.2f} EUR")
    print(f"  Imported energy:         {row['imported_energy_kwh']:.2f} kWh")
    print(f"  Exported energy:         {row['exported_energy_kwh']:.2f} kWh")
    print(f"  DG energy:               {row['dg_energy_kwh']:.2f} kWh")
    print(f"  Final BESS SoC:          {row['final_bess_soc']:.3f} p.u.")
    print(f"  Final HSS SoH:           {row['final_hss_soh']:.3f} p.u.")
    print(f"  Comfort violation sum:   {row['comfort_violation_degC_sum']:.4f} degC")
    print(f"  PEV target satisfied:    {row['pev_target_satisfied']} ({row['final_pev_soc']:.3f}/{row['pev_target']:.3f})")


def main() -> None:
    """Load datasets, run all scenarios, save outputs, and print summaries."""

    warnings.filterwarnings("default", category=RuntimeWarning)
    base_params = default_params()
    output_dir = ensure_dir(base_params.output_dir)

    print("Loading datasets...")
    data = load_project_data(base_params.data_dir, use_forecast=True)

    summaries: list[pd.DataFrame] = []
    scenario_results: dict[str, pd.DataFrame] = {}
    for scenario in default_scenarios(n_steps=48):
        params = replace(base_params, c_f=scenario.c_f)
        print(f"\nRunning {scenario.name} from index {scenario.start_index} for {scenario.n_steps} h...")
        df = run_mpc(params, data, scenario.start_index, scenario.n_steps, scenario.name)
        summary = summarize_results(df, params)
        save_results(df, summary, output_dir, scenario.name)
        save_plots(df, summary, output_dir, scenario.name)
        save_presentation_plots(df, summary, params, output_dir, scenario.name)
        summaries.append(summary)
        scenario_results[scenario.name] = df
        _print_summary(summary)

    all_summaries = pd.concat(summaries, ignore_index=True)
    all_summaries.to_csv(output_dir / "summary_all_scenarios.csv", index=False)
    save_presentation_overview(all_summaries, scenario_results, output_dir)
    print(f"\nSaved CSV files and plots in: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
