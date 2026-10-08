"""Independent response check with an NTSB *relative* pressure-drop shape.

This does not train, calibrate, or claim to reproduce the Cheyenne pipeline.
It maps a unitless pressure ratio onto a GasLib surrogate solely to check
whether the existing mechanics respond as expected at the documented times.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

from .io import simulate_to_directory

START = dt.datetime(2025, 9, 20, 23, 5)
END = dt.datetime(2025, 9, 20, 23, 25)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write(path: Path, fields: list[str], rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(root: Path = Path("outputs/ntsb_pressure_audit_v1/holdout_stress")) -> dict:
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"holdout output must be new or empty: {root}")
    parent = root.parent
    source_path = parent / "west_spill_1067220/pressure.csv"
    config_path = Path("outputs/sourced_v1_inland_desert_summer_2024/config.json")
    forcing_path = Path("outputs/sourced_v1_inland_desert_summer_2024/forcing.csv")
    _, source_rows = _rows(source_path)
    fields, base_rows = _rows(forcing_path)
    base = dict(base_rows[0])
    base_pressure = float(base["pressure_pa"])
    sample = [(dt.datetime.fromisoformat(row["source_local_time"]), float(row["source_value"]))
              for row in source_rows if START <= dt.datetime.fromisoformat(row["source_local_time"]) <= END]
    if len(sample) != 11 or sample[0] != (START, 810.0) or sample[-1] != (END, 711.1):
        raise ValueError("NTSB holdout window has changed; review original exhibit")
    if any((later[0] - earlier[0]) != dt.timedelta(minutes=2)
           for earlier, later in zip(sample, sample[1:])):
        raise ValueError("holdout window is not evenly sampled at two minutes")
    root.mkdir(parents=True)
    candidate, control = [], []
    for moment, value in sample:
        row = dict(base)
        row["timestamp_s"] = str(int((moment - START).total_seconds()))
        row["pressure_pa"] = str(base_pressure * value / 810.0)
        row["event_type"] = "normal_operation"
        candidate.append(row)
        reference_row = dict(row)
        reference_row["pressure_pa"] = str(base_pressure)
        control.append(reference_row)
    candidate_file = root / "pressure_drop_forcing.csv"
    control_file = root / "constant_pressure_control_forcing.csv"
    _write(candidate_file, fields, candidate)
    _write(control_file, fields, control)
    simulate_to_directory(config_path, candidate_file, root / "pressure_drop_sim", 42)
    simulate_to_directory(config_path, control_file, root / "control_sim", 42)
    _, shocked = _rows(root / "pressure_drop_sim/latent.csv")
    _, baseline = _rows(root / "control_sim/latent.csv")
    if len(shocked) != len(baseline) or len(shocked) != len(sample):
        raise ValueError("stress and control output lengths differ")
    first, last = shocked[0], shocked[-1]
    control_last = baseline[-1]
    report = {
        "status": "holdout response check; not calibration or training",
        "source_channel": "NTSB West Spill 1067220; PDF omits numeric unit",
        "source_window_local_as_printed": [str(START), str(END)],
        "source_window_row_count": len(sample),
        "source_csv_sha256": _hash(source_path),
        "gaslib_forcing_sha256": _hash(forcing_path),
        "config_sha256": _hash(config_path),
        "mapping": "GasLib initial pressure Pa multiplied by each NTSB source value / 810.0; no assumed source unit",
        "pressure_drop_percent_at_end": (float(candidate[-1]["pressure_pa"]) / base_pressure - 1) * 100,
        "true_hoop_strain_microstrain_start": float(first["strain_hoop_microstrain_true"]),
        "true_hoop_strain_microstrain_end_stress": float(last["strain_hoop_microstrain_true"]),
        "true_hoop_strain_microstrain_end_control": float(control_last["strain_hoop_microstrain_true"]),
        "end_hoop_strain_difference_microstrain": (
            float(last["strain_hoop_microstrain_true"])
            - float(control_last["strain_hoop_microstrain_true"])),
        "training_used": False,
        "claim_limit": "only verifies model's mechanical response to a pressure input; no saddle measurement or leak-detection performance",
    }
    (root / "stress_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
