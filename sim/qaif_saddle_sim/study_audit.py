"""Audit scenario invariants and connected source groups before any training."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .evidence_registry import sha256
from .io import read_forcing
from .config import Config
from .replay_grid import mechanical_stress_guard

CHANNELS = ("strain_hoop_microstrain", "strain_axial_microstrain", "temperature_k", "wetness_index")
PHYSICAL = ("steel_temperature_k", "coating_temperature_k", "coating_surface_temperature_k",
            "wetness_true", "pressure_hoop_stress_pa", "pressure_axial_stress_pa",
            "strain_hoop_microstrain_true", "strain_axial_microstrain_true")
FORBIDDEN = {"event_type", "case_id", "asset_id", "site_id", "phase_id", "run_id",
             "source_episode_id", "variant_id", "source_pages", "upstream_pressure_ratio",
             "wet_path_open", "wetness_true", "mechanism_id", "intervention_applied"}


def rows(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_run(directory: str | Path, sample_period_s: int, stress_budget_pa: float) -> dict:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["training_ready"] is not False:
        raise ValueError("research run cannot declare training readiness")
    for name, digest in manifest["output_files"].items():
        if sha256(directory/name) != digest:
            raise ValueError("run snapshot/output hash mismatch")
    observed, context, latent = (rows(directory/name) for name in ("observed.csv", "context.csv", "latent.csv"))
    forcing = read_forcing(directory / "forcing_snapshot.csv")
    config = Config.from_json(directory / "config_snapshot.json")
    if len({len(observed),len(context),len(latent),len(forcing),manifest["sample_count"]}) != 1:
        raise ValueError("study run row counts differ")
    if not observed or FORBIDDEN & (set(observed[0]) | set(context[0])):
        raise ValueError("study metadata leaked to observed/context")
    max_stress = 0.0
    for i, (obs, ctx, state, step) in enumerate(zip(observed, context, latent, forcing)):
        expected_time = i * sample_period_s
        if any(float(row["timestamp_s"]) != expected_time for row in (obs,ctx,state)) or step.timestamp_s != expected_time:
            raise ValueError("study time grid differs across outputs")
        if obs["packet_valid"] not in {"True", "False"}:
            raise ValueError("invalid packet validity value")
        valid = obs["packet_valid"] == "True"
        if valid and any(not obs[k] or not math.isfinite(float(obs[k])) for k in CHANNELS):
            raise ValueError("valid study packet lacks finite channels")
        if not valid and any(obs[k] for k in CHANNELS):
            raise ValueError("invalid study packet contains readings")
        if valid and not 0 <= float(obs["wetness_index"]) <= 1:
            raise ValueError("wetness outside observation bounds")
        if any(not math.isfinite(float(state[k])) for k in PHYSICAL) or not 0 <= float(state["wetness_true"]) <= 1:
            raise ValueError("invalid latent physics")
        max_stress = max(max_stress, mechanical_stress_guard(config, step, float(state["steel_temperature_k"]),stress_budget_pa))
    return {"sample_count":len(observed),"valid_packet_count":sum(r["packet_valid"]=="True" for r in observed),
            "max_von_mises_stress_pa":max_stress,"research_stress_budget_pa":stress_budget_pa,
            "numerically_clean":True,"training_ready":False}


def audit_pair(directory: str | Path, physical_start_s: float, period_s: int,
               stress_budget_pa: float, mechanism: str) -> dict:
    directory = Path(directory)
    manifest = json.loads((directory/"paired_manifest.json").read_text(encoding="utf-8"))
    if manifest["training_ready"] is not False:
        raise ValueError("pair cannot claim training readiness")
    reference = directory / "inputs/reference_manifest_snapshot.json"
    if sha256(reference) != manifest["reference_manifest_snapshot_sha256"]:
        raise ValueError("parent reference snapshot changed")
    sample_labels = directory / "inputs/timeline_samples.csv"
    if sha256(sample_labels) != manifest["timeline_samples_sha256"]:
        raise ValueError("timeline sample labels changed")
    spec = json.loads((directory/"inputs/timeline_spec.json").read_text(encoding="utf-8"))
    if spec != manifest["intervention_spec"]:
        raise ValueError("timeline spec differs from pair manifest")
    control_audit = audit_run(directory/"control",period_s,stress_budget_pa)
    intervention_audit = audit_run(directory/"intervention",period_s,stress_budget_pa)
    control_obs, event_obs = rows(directory/"control/observed.csv"), rows(directory/"intervention/observed.csv")
    control_lat, event_lat = rows(directory/"control/latent.csv"), rows(directory/"intervention/latent.csv")
    control_ctx, event_ctx = rows(directory/"control/context.csv"), rows(directory/"intervention/context.csv")
    control_steps = read_forcing(directory/"control/forcing_snapshot.csv")
    event_steps = read_forcing(directory/"intervention/forcing_snapshot.csv")
    if control_ctx != event_ctx:
        raise ValueError("matched pair differs in model-facing environment/operation context")
    for i, step in enumerate(control_steps):
        if step.timestamp_s <= physical_start_s:
            if control_obs[i] != event_obs[i] or control_steps[i] != event_steps[i]:
                raise ValueError("pre-intervention readings/forcing differ")
            if any(control_lat[i][key] != event_lat[i][key] for key in PHYSICAL):
                raise ValueError("pre-intervention physical state differs")
    physics_identical = all(all(a[k] == b[k] for k in PHYSICAL) for a,b in zip(control_lat,event_lat))
    if mechanism == "sensor_fault" and not physics_identical:
        raise ValueError("sensor fault changed underlying pipe physics")
    forced_times=[step.timestamp_s for step in event_steps if step.force_missing]
    if forced_times and any(a!=b for a,b in zip(control_obs,event_obs)
                            if float(a["timestamp_s"])>max(forced_times)):
        raise ValueError("forced packet loss changed the random readout stream after recovery")
    if mechanism == "interface_wetting":
        wet_delta = max(float(b["wetness_true"])-float(a["wetness_true"]) for a,b in zip(control_lat,event_lat))
        if wet_delta <= 0:
            raise ValueError("wetting scenario lacks an actual wetness state change")
        if any(a[k]!=b[k] for a,b in zip(control_lat,event_lat) for k in PHYSICAL if k != "wetness_true"):
            raise ValueError("wetting scenario changed unrelated physical channels")
    if mechanism == "mechanical_change":
        if max(abs(float(b["strain_axial_microstrain_true"])-float(a["strain_axial_microstrain_true"]))
               for a,b in zip(control_lat,event_lat)) == 0:
            raise ValueError("mechanical scenario has no axial strain effect")
    return {"control":control_audit,"intervention":intervention_audit,
            "pre_intervention_identical":True,"context_identical":True,
            "physical_states_identical":physics_identical,"training_ready":False}


def connected_groups(records: list[dict]) -> list[dict]:
    """Shared source tokens join records transitively before assigning splits."""
    ids = [r["record_id"] for r in records]
    if len(ids)!=len(set(ids)) or any(not r.get("source_tokens") for r in records):
        raise ValueError("study records need unique ids and source tokens")
    parent=list(range(len(records)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    owners={}
    for i, record in enumerate(records):
        for token in record["source_tokens"]:
            if token in owners:
                parent[find(i)]=find(owners[token])
            else:
                owners[token]=i
    groups={}
    for i, record in enumerate(records):
        groups.setdefault(find(i),[]).append(record)
    return [{"group_id":f"source_component_{index:03d}","record_ids":sorted(r["record_id"] for r in members),
             "source_tokens":sorted({token for r in members for token in r["source_tokens"]})}
            for index,members in enumerate(groups.values())]


def validate_split_assignment(groups: list[dict], assignments: dict[str,str]) -> None:
    ids={identifier for group in groups for identifier in group["record_ids"]}
    if set(assignments)!=ids:
        raise ValueError("split assignment must cover every record exactly")
    for group in groups:
        if len({assignments[r] for r in group["record_ids"]})!=1:
            raise ValueError("connected source component crosses split boundaries")


def compare_channels(before: list[dict], after: list[dict]) -> dict:
    if len(before)!=len(after):
        raise ValueError("sensitivity row counts differ")
    result={}
    for key in CHANNELS:
        differences=[float(b[key])-float(a[key]) for a,b in zip(before,after)
                     if a["packet_valid"]==b["packet_valid"]=="True"]
        if not differences:
            raise ValueError("no common valid samples for sensitivity comparison")
        result[key]={"common_valid_count":len(differences),"max_abs_delta":max(abs(v) for v in differences),
                     "rmse_delta":math.sqrt(sum(v*v for v in differences)/len(differences))}
    return result
