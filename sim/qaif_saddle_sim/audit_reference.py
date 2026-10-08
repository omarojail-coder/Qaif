"""Numerical and provenance audit for one prepared reference simulation."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

from .pressure_profile import NTSB_HOLDOUT_START


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pressure_variability(values: list[float]) -> dict:
    """Own-median normalized hourly metrics; initialization row excluded by caller."""
    if not values or any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("pressure metrics need positive finite hourly values")
    median = statistics.median(values)
    deltas = sorted(abs(b - a) for a, b in zip(values, values[1:]))
    if deltas:
        position = (len(deltas) - 1) * 0.95
        low = int(position)
        high = min(low + 1, len(deltas) - 1)
        q95 = deltas[low] + (deltas[high] - deltas[low]) * (position - low)
    else:
        q95 = 0.0
    daily = [abs(b - a) for a, b in zip(values, values[24:])]
    return {
        "hour_count": len(values),
        "median_native": median,
        "range_over_own_median_pct": 100 * (max(values) - min(values)) / median,
        "median_abs_hourly_delta_over_own_median_pct": 100 * statistics.median(deltas) / median if deltas else 0,
        "p95_abs_hourly_delta_over_own_median_pct": 100 * q95 / median,
        "lag24_pair_count": len(daily),
        "lag24_exact_match_fraction": sum(v == 0 for v in daily) / len(daily) if daily else None,
        "lag24_max_abs_native_difference": max(daily) if daily else None,
    }


def audit_reference(prepared_dir: str | Path, simulated_dir: str | Path) -> dict:
    prepared_dir, simulated_dir = Path(prepared_dir), Path(simulated_dir)
    reference = json.loads((prepared_dir / "reference_manifest.json").read_text(encoding="utf-8"))
    simulation = json.loads((simulated_dir / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in reference["output_sha256"].items():
        if _hash(prepared_dir / name) != expected:
            raise ValueError(f"prepared file changed: {name}")
    for name, expected in simulation["output_files"].items():
        if _hash(simulated_dir / name) != expected:
            raise ValueError(f"simulation file changed: {name}")
    if (simulation["reference_manifest_sha256"] is None
            or simulation["source_episode_id"] != reference["episode_id"]):
        raise ValueError("simulation is not linked to this reference episode")
    snapshot = json.loads((simulated_dir / "reference_manifest_snapshot.json").read_text(encoding="utf-8"))
    if snapshot != reference:
        raise ValueError("simulation reference snapshot differs from prepared manifest")
    observed = _rows(simulated_dir / "observed.csv")
    context = _rows(simulated_dir / "context.csv")
    latent = _rows(simulated_dir / "latent.csv")
    forcing = _rows(prepared_dir / "forcing.csv")
    if (not observed or len({len(observed), len(context), len(latent), len(forcing)}) != 1
            or len(observed) != reference["sample_count"]):
        raise ValueError("row counts do not match")
    forbidden = {"event_type", "asset_id", "run_id", "source_episode_id",
                 "wet_path_open", "wetness_true", "bending_moment_nm",
                 "pressure_source_local_hour", "source_native_hourly_median",
                 "upstream_pressure_ratio", "channel_id", "source_pages"}
    if forbidden & (set(observed[0]) | set(context[0])):
        raise ValueError("generator metadata leaked into model-facing outputs")
    times = [float(row["timestamp_s"]) for row in observed]
    if (times[0] != 0 or any(b - a != reference["sample_period_s"]
                             for a, b in zip(times, times[1:]))):
        raise ValueError("time grid is not the expected hourly grid")
    for index in range(len(observed)):
        if not all(float(rows[index]["timestamp_s"]) == times[index]
                   for rows in (context, latent, forcing)):
            raise ValueError("observed/context/latent/forcing timestamps misalign")
        valid = observed[index]["packet_valid"] == "True"
        keys = ("strain_hoop_microstrain", "strain_axial_microstrain",
                "temperature_k", "wetness_index")
        if valid:
            if any(not observed[index][key] or not math.isfinite(float(observed[index][key]))
                   for key in keys):
                raise ValueError("valid packet has missing or nonfinite channel")
            wetness = float(observed[index]["wetness_index"])
            if not 0 <= wetness <= 1:
                raise ValueError("wetness observation outside [0,1]")
        elif any(observed[index][key] for key in keys):
            raise ValueError("invalid packet still contains readings")
    valid_rows = [row for row in observed if row["packet_valid"] == "True"]
    profile = reference.get("pressure_profile", {"mode": "periodic_benchmark_surrogate"})
    pressure_checks = []
    if profile["mode"] == "ntsb_relative_upstream":
        hours = _rows(prepared_dir / "pressure_hourly_snapshot.csv")
        diagnostics = _rows(prepared_dir / "source_diagnostics.csv")
        if len(hours) != reference["weather_interval_count"] or len(diagnostics) != len(forcing):
            raise ValueError("pressure profile counts do not match weather/forcing")
        # Reapply source-window and normalization constraints, keeping source
        # clocks out of observed/context. Hash checks above protect snapshots.
        start = dt.datetime.fromisoformat(profile["window_start_local_inclusive"])
        end = dt.datetime.fromisoformat(profile["window_end_local_exclusive"])
        cutoff = NTSB_HOLDOUT_START
        if end > cutoff or end - start != dt.timedelta(hours=len(hours)):
            raise ValueError("pressure profile window overlaps holdout or has wrong duration")
        anchor = float(hours[0]["source_native_hourly_median"])
        for i, row in enumerate(hours):
            if dt.datetime.fromisoformat(row["source_local_hour"]) != start + dt.timedelta(hours=i):
                raise ValueError("pressure source hours are not consecutive")
            expected_ratio = float(row["source_native_hourly_median"]) / anchor
            if not math.isclose(float(row["upstream_pressure_ratio"]), expected_ratio, rel_tol=1e-12):
                raise ValueError("pressure normalization mismatch")
        for i, row in enumerate(diagnostics):
            source_hour = hours[max(0, i - 1)]
            expected_upstream = (reference["initial_upstream_absolute_pressure_pa"]
                                 * float(source_hour["upstream_pressure_ratio"]))
            if (row["pressure_source_local_hour"] != source_hour["source_local_hour"]
                    or not math.isclose(float(row["surrogate_upstream_absolute_pressure_pa"]),
                                        expected_upstream, rel_tol=1e-12)):
                raise ValueError("pressure source-to-forcing alignment mismatch")
        pressure_checks = ["pressure_source_consecutive_hours", "incident_window_excluded",
                           "pressure_ratio_mapping", "pressure_metadata_separated"]
    return {
        "episode_id": reference["episode_id"],
        "sample_count": len(observed),
        "valid_packet_count": len(valid_rows),
        "rain_hours": reference["quality_summary"]["rain_hours"],
        "temperature_c_range": [
            min(float(row["temperature_k"]) for row in valid_rows) - 273.15,
            max(float(row["temperature_k"]) for row in valid_rows) - 273.15,
        ],
        "hoop_microstrain_range": [
            min(float(row["strain_hoop_microstrain"]) for row in valid_rows),
            max(float(row["strain_hoop_microstrain"]) for row in valid_rows),
        ],
        "checks": ["prepared_hashes", "output_hashes", "aligned_hourly_grid",
                   "finite_valid_channels", "missing_packet_contract", "no_label_leakage",
                   *pressure_checks],
        "pressure_mode": profile["mode"],
        "pressure_variability": pressure_variability([float(row["pressure_pa"]) for row in forcing[1:]]),
        "flow_mode": reference.get("flow_profile", {}).get("mode", "periodic_trr154_demand_surrogate"),
        "numerically_clean": True,
        "training_ready": False,
        "training_limit": "No saddle calibration, representative local gas operation, or group-level evaluation.",
    }
