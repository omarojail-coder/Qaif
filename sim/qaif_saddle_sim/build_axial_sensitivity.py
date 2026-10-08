"""Reproducible 0/100/1000 m axial-exchange comparison on two archived weeks.

This is a scenario sensitivity study, not a calibration or training dataset.
Run from the project root with: python -m qaif_saddle_sim.build_axial_sensitivity
"""

from __future__ import annotations

import json
import csv
from pathlib import Path

from .audit_reference import audit_reference
from .io import simulate_to_directory
from .reference_episode import prepare_reference_episode


def main() -> None:
    root = Path(__file__).resolve().parent
    output_root = root.parent / "outputs" / "axial_sensitivity_v2"
    if output_root.exists():
        raise FileExistsError(f"sensitivity output already exists: {output_root}")
    sources = root / "reference_data"
    template = root / "examples" / "reference_template_config.json"
    choices = {
        0: root / "examples" / "reference_gas_assumptions.json",
        100: root / "examples" / "reference_gas_assumptions_100m.json",
        1000: root / "examples" / "reference_gas_assumptions_1000m.json",
    }
    episodes = ("inland_desert_summer_2024", "red_sea_coast_summer_2024")
    comparisons = []
    for episode_index, episode in enumerate(episodes):
        for exposure_m, assumptions in choices.items():
            item = output_root / episode / f"exposure_{exposure_m}m"
            prepared = item / "prepared"
            simulated = item / "simulated"
            reference = prepare_reference_episode(
                sources, episode, template, prepared, assumptions
            )
            # Hold readout noise and packet-loss draws fixed within each
            # episode, while changing the seed between independent episodes.
            seed = 521 + 31 * episode_index
            simulate_to_directory(prepared / "config.json", prepared / "forcing.csv",
                                  simulated, seed)
            report = audit_reference(prepared, simulated)
            with (simulated / "latent.csv").open(newline="", encoding="utf-8") as handle:
                latent_rows = list(csv.DictReader(handle))
            comparisons.append({
                "episode": episode,
                "effective_axial_exposure_length_m": exposure_m,
                "seed": seed,
                "local_gas_temperature_c_range": reference["quality_summary"]
                ["local_gas_temperature_c_range"],
                "sensor_temperature_c_range": report["temperature_c_range"],
                "true_steel_temperature_c_range": [
                    min(float(row["steel_temperature_k"]) - 273.15 for row in latent_rows),
                    max(float(row["steel_temperature_k"]) - 273.15 for row in latent_rows),
                ],
                "hoop_microstrain_range": report["hoop_microstrain_range"],
                "true_hoop_microstrain_range": [
                    min(float(row["strain_hoop_microstrain_true"]) for row in latent_rows),
                    max(float(row["strain_hoop_microstrain_true"]) for row in latent_rows),
                ],
                "valid_packet_count": report["valid_packet_count"],
                "numerically_clean": report["numerically_clean"],
                "training_ready": report["training_ready"],
            })
    summary = {
        "purpose": "unvalidated axial exposure sensitivity, not fault training",
        "episode_count": len(episodes),
        "scenario_count": len(comparisons),
        "same_weather_cell_assumed_over_exposed_length": True,
        "same_noise_seed_within_episode_for_paired_sensitivity": True,
        "real_route_exposure_length_known": False,
        "comparisons": comparisons,
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output_root": str(output_root),
                      "scenario_count": len(comparisons)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
