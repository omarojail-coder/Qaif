"""Evidence-linked, multi-phase interventions over a shared baseline episode."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

from .case_registry import load_case
from .config import Config
from .experiment import BOOL_FIELDS, EVENT_OVERRIDES, export_pair
from .io import load_reference_provenance, read_forcing
from .model import Step


def _object(value: object, required: set[str], optional: set[str], name: str) -> dict:
    if not isinstance(value, dict) or required - value.keys() or value.keys() - required - optional:
        raise ValueError(f"{name} requires {sorted(required)}; optional {sorted(optional)}")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _profile_value(profile: object, field_name: str, fraction: float) -> float | bool:
    profile = _object(profile, {"mode"}, {"value", "from", "to", "base", "peak", "peak_fraction"},
                      f"profile {field_name}")
    mode = profile["mode"]
    if mode == "hold":
        _object(profile, {"mode", "value"}, set(), f"profile {field_name}")
        value = profile["value"]
        if field_name in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} requires a boolean hold value")
            return value
        return _number(value, field_name)
    if field_name in BOOL_FIELDS:
        raise ValueError(f"{field_name} supports hold only")
    if mode == "linear":
        _object(profile, {"mode", "from", "to"}, set(), f"profile {field_name}")
        start = _number(profile["from"], f"{field_name}.from")
        end = _number(profile["to"], f"{field_name}.to")
        return start + (end - start) * fraction
    if mode == "pulse":
        _object(profile, {"mode", "base", "peak", "peak_fraction"}, set(), f"profile {field_name}")
        base = _number(profile["base"], f"{field_name}.base")
        peak = _number(profile["peak"], f"{field_name}.peak")
        peak_fraction = _number(profile["peak_fraction"], f"{field_name}.peak_fraction")
        if not 0 < peak_fraction < 1:
            raise ValueError("peak_fraction must be strictly between 0 and 1")
        weight = (fraction / peak_fraction if fraction <= peak_fraction
                  else (1 - fraction) / (1 - peak_fraction))
        return base + (peak - base) * weight
    raise ValueError(f"unknown profile mode: {mode}")


def build_timeline(config: Config, control_steps: list[Step], spec: object
                   ) -> tuple[list[Step], list[dict[str, object]], dict[str, int], dict[str, object] | None]:
    """Validate a timeline and return intervention steps plus audit-only sample labels."""
    spec = _object(spec, {"schema_version", "asset_id", "site_id", "base_episode_id",
                          "scenario_family_id", "mechanism_id", "phases"},
                   {"inspired_by_case_id", "evidence_level", "unknown_assumptions"}, "timeline")
    if spec["schema_version"] != "1":
        raise ValueError("unsupported timeline schema_version")
    for name in ("asset_id", "site_id", "base_episode_id", "scenario_family_id", "mechanism_id"):
        _identifier(spec[name], name)
    if spec["asset_id"] != config.asset_id or spec["base_episode_id"] != config.source_episode_id:
        raise ValueError("timeline asset_id/base_episode_id must match config")
    mechanism_id = spec["mechanism_id"]
    if mechanism_id not in EVENT_OVERRIDES:
        raise ValueError(f"unsupported mechanism_id: {mechanism_id}")
    if "evidence_level" in spec:
        _identifier(spec["evidence_level"], "evidence_level")
    if "unknown_assumptions" in spec:
        assumptions = spec["unknown_assumptions"]
        if not isinstance(assumptions, list):
            raise ValueError("unknown_assumptions must be a list")
        for assumption in assumptions:
            _identifier(assumption, "unknown_assumptions item")
    if not control_steps or any(step.event_type not in {"normal_operation", "normal_environment"}
                                for step in control_steps):
        raise ValueError("timeline baseline must contain only normal episodes")
    phases = spec["phases"]
    if not isinstance(phases, list) or not phases:
        raise ValueError("timeline phases must be a nonempty list")
    case = (load_case(spec["inspired_by_case_id"], mechanism_id)
            if "inspired_by_case_id" in spec else None)
    event_steps = list(control_steps)
    labels: list[dict[str, object]] = [{
        "timestamp_s": step.timestamp_s,
        "phase_id": "",
        "event_type": "",
        "intervention_applied": False,
        "changed_fields": "",
    } for step in control_steps]
    counts: dict[str, int] = {}
    previous_end = -math.inf
    names: set[str] = set()
    primary_phase_changed = False
    for index, raw_phase in enumerate(phases):
        phase = _object(raw_phase, {"phase_id", "event_type", "start_s", "end_s", "changes"},
                        set(), f"phase {index}")
        phase_id = _identifier(phase["phase_id"], "phase_id")
        if phase_id in names:
            raise ValueError(f"duplicate phase_id: {phase_id}")
        names.add(phase_id)
        event_type = phase["event_type"]
        if event_type not in EVENT_OVERRIDES:
            raise ValueError(f"unsupported event_type in phase {phase_id}")
        start = _number(phase["start_s"], f"{phase_id}.start_s")
        end = _number(phase["end_s"], f"{phase_id}.end_s")
        if start < 0 or end <= start or start < previous_end:
            raise ValueError("timeline phases must be positive, sorted and non-overlapping")
        previous_end = end
        changes = phase["changes"]
        if not isinstance(changes, dict) or changes.keys() - EVENT_OVERRIDES[event_type]:
            raise ValueError(f"phase {phase_id} changes do not match {event_type}")
        observation_only = not changes
        if observation_only and event_type not in {"normal_operation", "normal_environment"}:
            raise ValueError(f"phase {phase_id} without changes must be a normal observation phase")
        # Validate profile extrema, including a pulse peak between samples.
        for field_name, profile in changes.items():
            fractions = [0.0, 1.0]
            if isinstance(profile, dict) and profile.get("mode") == "pulse":
                fractions.append(_number(profile.get("peak_fraction"),
                                         f"{field_name}.peak_fraction"))
            for fraction in fractions:
                value = _profile_value(profile, field_name, fraction)
                replace(control_steps[0], **{field_name: value}).validate()
        phase_count = 0
        matched = 0
        for row_index, control in enumerate(control_steps):
            t = control.timestamp_s
            if not start <= t < end:
                continue
            matched += 1
            fraction = (t - start) / (end - start)
            overrides = {name: _profile_value(profile, name, fraction)
                         for name, profile in changes.items()}
            changed = sorted(name for name, value in overrides.items()
                             if getattr(control, name) != value)
            labels[row_index]["phase_id"] = phase_id
            if changed:
                modified = replace(control, **overrides, event_type=event_type)
                modified.validate()
                event_steps[row_index] = modified
                labels[row_index]["event_type"] = event_type
                labels[row_index]["intervention_applied"] = True
                labels[row_index]["changed_fields"] = ";".join(changed)
                phase_count += 1
        if not matched or (not observation_only and not phase_count):
            raise ValueError(f"phase {phase_id} does not change any sampled input")
        counts[phase_id] = phase_count
        primary_phase_changed |= event_type == mechanism_id and phase_count > 0
    if not primary_phase_changed:
        raise ValueError("timeline must change samples in a phase matching mechanism_id")
    if not sum(counts.values()):
        raise ValueError("timeline must change at least one sampled input")
    if mechanism_id == "interface_wetting" and not any(
        label["event_type"] == "interface_wetting" and step.wet_path_open and step.wet_drive > 0
        for label, step in zip(labels, event_steps)
    ):
        raise ValueError("interface_wetting requires an open path and positive wet drive")
    return event_steps, labels, counts, case


def make_timeline_pair(config_path: str | Path, forcing_path: str | Path,
                       timeline_path: str | Path, output_dir: str | Path,
                       seed: int) -> dict[str, object]:
    config = Config.from_json(config_path)
    control_steps = read_forcing(forcing_path)
    reference = load_reference_provenance(config_path, forcing_path)
    spec = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    event_steps, labels, counts, case = build_timeline(config, control_steps, spec)
    split_group = json.dumps([config.asset_id, spec["site_id"], config.source_episode_id],
                             ensure_ascii=False, separators=(",", ":"))
    manifest = export_pair(
        config, control_steps, event_steps, output_dir, seed, spec,
        spec["mechanism_id"], sum(counts.values()), case,
        split_group=split_group,
        extra_manifest={
            "timeline_schema_version": "1",
            "site_id": spec["site_id"],
            "base_episode_id": spec["base_episode_id"],
            "scenario_family_id": spec["scenario_family_id"],
            "mechanism_id": spec["mechanism_id"],
            "phase_sample_counts": counts,
            "evidence_level": spec.get("evidence_level"),
            "unknown_assumptions": spec.get("unknown_assumptions", []),
            "timeline_scope": "local input interventions; no spatial damage propagation",
        },
        spec_filename="timeline_spec.json",
        reference_provenance=reference,
    )
    output_dir = Path(output_dir)
    labels_path = output_dir / "inputs" / "timeline_samples.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]))
        writer.writeheader()
        writer.writerows(labels)
    manifest["timeline_samples_sha256"] = hashlib.sha256(labels_path.read_bytes()).hexdigest()
    (output_dir / "paired_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest
