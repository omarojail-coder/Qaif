"""Matched control/intervention episodes with explicit, auditable changes."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, fields, replace
from pathlib import Path

from .config import Config
from .case_registry import load_case
from .io import load_reference_provenance, read_forcing, simulate_to_directory
from .model import Step
from . import __version__

EVENT_OVERRIDES = {
    "mechanical_change": {"bending_moment_nm", "bending_direction_rad"},
    "interface_wetting": {"wet_drive", "wet_path_open", "drying_rate_multiplier"},
    "sensor_fault": {"hoop_coupling_multiplier", "axial_coupling_multiplier",
                     "temperature_flatline", "wetness_flatline", "force_missing"},
    "normal_environment": {"ambient_temperature_k", "sky_temperature_k", "solar_w_m2",
                           "solar_incidence", "h_outer_w_m2k", "wet_drive",
                           "drying_rate_multiplier"},
    "normal_operation": {"pressure_pa", "fluid_temperature_k", "h_inner_w_m2k"},
}
BOOL_FIELDS = {"wet_path_open", "temperature_flatline", "wetness_flatline", "force_missing"}


def _write_steps(path: Path, steps: list[Step]) -> None:
    names = [field.name for field in fields(Step)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for step in steps:
            row = asdict(step)
            for name in BOOL_FIELDS:
                row[name] = int(row[name])
            writer.writerow(row)


def export_pair(config: Config, control_steps: list[Step], event_steps: list[Step],
                output_dir: str | Path, seed: int, spec: dict[str, object],
                event_type: str, altered_count: int, case: dict[str, object] | None,
                *, split_group: str | None = None,
                extra_manifest: dict[str, object] | None = None,
                spec_filename: str | None = None,
                reference_provenance: dict | None = None,
                physics_cache=None) -> dict[str, object]:
    """Write matched branches through the same simulator and preserve provenance."""
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    control_config = replace(config, run_id=f"{config.run_id}_control")
    event_config = replace(config, run_id=f"{config.run_id}_intervention")
    control_config_path = inputs / "control_config.json"
    event_config_path = inputs / "intervention_config.json"
    control_forcing_path = inputs / "control_forcing.csv"
    event_forcing_path = inputs / "intervention_forcing.csv"
    control_config_path.write_text(json.dumps(asdict(control_config), indent=2) + "\n", encoding="utf-8")
    event_config_path.write_text(json.dumps(asdict(event_config), indent=2) + "\n", encoding="utf-8")
    _write_steps(control_forcing_path, control_steps)
    _write_steps(event_forcing_path, event_steps)
    if spec_filename is not None:
        (inputs / spec_filename).write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    reference_sha256 = None
    if reference_provenance is not None:
        reference_path = inputs / "reference_manifest_snapshot.json"
        reference_path.write_text(
            json.dumps(reference_provenance, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        reference_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    case_snapshot_sha256 = None
    if case is not None:
        case_snapshot_path = inputs / "case_card_snapshot.json"
        case_snapshot_path.write_text(
            json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        case_snapshot_sha256 = hashlib.sha256(case_snapshot_path.read_bytes()).hexdigest()
    control_manifest = simulate_to_directory(control_config_path, control_forcing_path,
                                              output_dir / "control", seed, physics_cache=physics_cache)
    event_manifest = simulate_to_directory(event_config_path, event_forcing_path,
                                            output_dir / "intervention", seed, physics_cache=physics_cache)
    pair_manifest: dict[str, object] = {
        "schema_version": "2",
        "generator_version": __version__,
        "source_episode_id": config.source_episode_id,
        "asset_id": config.asset_id,
        "seed": seed,
        "event_type": event_type,
        "event_sample_count": altered_count,
        "intervention_spec": spec,
        "inspired_by_case_id": case["case_id"] if case is not None else None,
        "case_record_type": case["record_type"] if case is not None else None,
        "case_source_url": case["source_url"] if case is not None else None,
        "case_card_snapshot_sha256": case_snapshot_sha256,
        "reference_manifest_snapshot_sha256": reference_sha256,
        "case_link_scope": "mechanism inspiration only; no historical sensor waveform" if case is not None else None,
        "control_run_id": control_manifest["run_id"],
        "intervention_run_id": event_manifest["run_id"],
        "split_group": split_group or f"{config.asset_id}:{config.source_episode_id}",
        "training_ready": False,
    }
    if extra_manifest:
        pair_manifest.update(extra_manifest)
    (output_dir / "paired_manifest.json").write_text(
        json.dumps(pair_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return pair_manifest


def make_pair(config_path: str | Path, forcing_path: str | Path, intervention_path: str | Path,
              output_dir: str | Path, seed: int) -> dict[str, object]:
    """Run both branches. Intervention JSON defines event, time interval, and set values."""
    config = Config.from_json(config_path)
    control_steps = read_forcing(forcing_path)
    reference = load_reference_provenance(config_path, forcing_path)
    if any(step.event_type not in {"normal_operation", "normal_environment"}
           for step in control_steps):
        raise ValueError("paired baseline forcing must contain only normal episodes")
    spec = json.loads(Path(intervention_path).read_text(encoding="utf-8"))
    required = {"event_type", "start_s", "end_s", "set"}
    if not required <= set(spec) or set(spec) - required - {"inspired_by_case_id"}:
        raise ValueError("intervention requires event_type, start_s, end_s, set; optional inspired_by_case_id")
    event_type = spec["event_type"]
    start_s, end_s = spec["start_s"], spec["end_s"]
    overrides = spec["set"]
    if event_type not in EVENT_OVERRIDES or not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
        raise ValueError("invalid event_type or time bounds")
    case = load_case(spec["inspired_by_case_id"], event_type) if "inspired_by_case_id" in spec else None
    if (not math.isfinite(start_s) or not math.isfinite(end_s)
            or not 0 <= start_s < end_s or not isinstance(overrides, dict) or not overrides):
        raise ValueError("intervention must have a nonempty change and a valid interval")
    if set(overrides) - EVENT_OVERRIDES[event_type]:
        raise ValueError(f"fields do not match {event_type}: "
                         f"{sorted(set(overrides) - EVENT_OVERRIDES[event_type])}")
    for name, value in overrides.items():
        if name in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be a JSON boolean")
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number")
    event_steps = []
    altered_count = 0
    for step in control_steps:
        if (start_s <= step.timestamp_s < end_s
                and any(getattr(step, key) != value for key, value in overrides.items())):
            modified = replace(step, **overrides, event_type=event_type)
            modified.validate()
            event_steps.append(modified)
            altered_count += 1
        else:
            event_steps.append(step)
    if not altered_count:
        raise ValueError("intervention must change at least one forcing sample")
    if (event_type == "interface_wetting"
            and not any(step.event_type == event_type and step.wet_path_open and step.wet_drive > 0
                        for step in event_steps)):
        raise ValueError("interface_wetting requires an open path and a positive wet drive")

    return export_pair(config, control_steps, event_steps, output_dir, seed, spec,
                       event_type, altered_count, case,
                       reference_provenance=reference)
