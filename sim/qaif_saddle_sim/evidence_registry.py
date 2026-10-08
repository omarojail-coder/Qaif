"""Explicit research grids, source coverage and aboveground site contracts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from .reference_episode import _checked_file, _gaslib_pipe_and_gas
from .config import Channel

STATUSES = {"archived_benchmark", "general_material_reference", "research_assumption",
            "initial_condition", "model_definition"}


def effective_config_fields(config_data: dict) -> dict:
    """Expand implicit Channel defaults so evidence coverage cannot omit them."""
    result=dict(config_data)
    for name in ("strain_hoop","strain_axial","temperature","wetness"):
        result[name]=asdict(Channel(**config_data[name]))
    return result


def numeric_leaves(data: dict, prefix: str = "") -> dict[str, float]:
    result = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(numeric_leaves(value, path))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[path] = value
    return result


def set_parameter(data: dict, path: str, value: float) -> None:
    parts = path.split(".")
    target = data
    for part in parts[:-1]:
        target = target[part]
    if not isinstance(target[parts[-1]], (int, float)) or isinstance(target[parts[-1]], bool):
        raise ValueError("parameter path must name a numeric field")
    target[parts[-1]] = value


def load_registry(path: str | Path, config_data: dict, gas_data: dict) -> dict:
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    if registry.get("schema_version") != "1" or registry.get("field_training_ready") is not False:
        raise ValueError("unsupported registry schema or field readiness")
    sources = registry.get("sources", {})
    entries = registry.get("parameters", [])
    if not isinstance(sources, dict) or not isinstance(entries, list) or not entries:
        raise ValueError("registry sources and parameters required")
    seen = set()
    for entry in entries:
        required = {"parameter_id", "scope", "path", "unit", "nominal", "sweep_values",
                    "sweep_min", "sweep_max", "range_kind", "evidence_status", "source_ids",
                    "qaif_calibrated", "transfer_limit", "needed_validation"}
        if not isinstance(entry, dict) or required - entry.keys():
            raise ValueError("parameter evidence record missing required fields")
        identifier = entry["parameter_id"]
        if identifier in seen or identifier != f"{entry['scope']}.{entry['path']}":
            raise ValueError("duplicate or inconsistent parameter_id")
        seen.add(identifier)
        if entry["scope"] not in {"config", "gas", "scenario"} or entry["evidence_status"] not in STATUSES:
            raise ValueError("unsupported parameter scope/evidence status")
        values = entry["sweep_values"]
        if (not isinstance(values, list) or not values
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in [entry["nominal"], entry["sweep_min"], entry["sweep_max"], *values])):
            raise ValueError("research grid must contain finite numeric values")
        if (len(set(values)) != len(values) or values != sorted(values)
                or entry["nominal"] not in values or min(values) != entry["sweep_min"]
                or max(values) != entry["sweep_max"]):
            raise ValueError("research grid bounds/nominal/ordering mismatch")
        expected_kind = "research_grid" if len(values) > 1 else "held_nominal"
        if entry["range_kind"] != expected_kind or entry["qaif_calibrated"] is not False:
            raise ValueError("grid semantics cannot claim physical calibration")
        if (not entry["source_ids"] or any(key not in sources for key in entry["source_ids"])
                or not all(isinstance(entry[key], str) and entry[key].strip()
                           for key in ("unit", "transfer_limit", "needed_validation"))):
            raise ValueError("parameter evidence source/limit/unit missing")
    expected = {"config." + key for key in numeric_leaves(effective_config_fields(config_data))} | {
        "gas." + key for key in numeric_leaves(gas_data)}
    covered = {entry["parameter_id"] for entry in entries if entry["scope"] != "scenario"}
    if expected != covered:
        raise ValueError(f"parameter coverage mismatch: missing={sorted(expected-covered)}, extra={sorted(covered-expected)}")
    return registry


def validate_nominals(registry: dict, config_data: dict, gas_data: dict) -> None:
    actual = {"config." + k: v for k, v in numeric_leaves(effective_config_fields(config_data)).items()}
    actual.update({"gas." + k: v for k, v in numeric_leaves(gas_data).items()})
    for entry in registry["parameters"]:
        if entry["scope"] != "scenario" and actual[entry["parameter_id"]] != entry["nominal"]:
            raise ValueError(f"effective reference nominal differs from registry: {entry['parameter_id']}")


def validate_profiles(path: str | Path, source_dir: str | Path) -> dict:
    profiles = json.loads(Path(path).read_text(encoding="utf-8"))
    source_dir = Path(source_dir)
    manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    if profiles.get("schema_version") != "1" or not isinstance(profiles.get("asset"), dict):
        raise ValueError("invalid profiles schema")
    asset = profiles["asset"]
    if asset.get("installation") != "aboveground" or asset.get("training_ready") is not False:
        raise ValueError("profile is outside the aboveground research scope")
    entry = manifest["entries"][asset["geometry_source_key"]]
    gas = _gaslib_pipe_and_gas(_checked_file(source_dir, entry))
    if (entry["sha256"] != asset["geometry_source_sha256"]
            or gas["pipe_id"] != asset["benchmark_pipe_id"] or gas["diameter_m"] != asset["inner_diameter_m"]):
        raise ValueError("asset geometry/source hash mismatch")
    if (asset["inner_diameter_m"] / asset["wall_thickness_m"] <= 20
            or not math.isfinite(asset["stress_budget_pa"]) or asset["stress_budget_pa"] <= 0):
        raise ValueError("asset thin-wall geometry/stress budget invalid")
    if not isinstance(profiles.get("sites"), list) or not profiles["sites"]:
        raise ValueError("at least one site profile required")
    seen = set()
    for site in profiles["sites"]:
        if site["site_id"] in seen:
            raise ValueError("duplicate site profile")
        seen.add(site["site_id"])
        if (site["installation"] != "aboveground" or site["actual_pipeline_site"] is not False
                or site["fault_incidence_prior"] is not None):
            raise ValueError("unsupported site installation or invented incidence prior")
        for key in [site["annual_weather_source_key"], *site["episode_source_keys"]]:
            source = manifest["entries"][key]
            file = _checked_file(source_dir, source)
            payload = json.loads(file.read_text(encoding="utf-8"))
            coordinates = payload["geometry"]["coordinates"]
            if (source["latitude"] != site["latitude"] or source["longitude"] != site["longitude"]
                    or coordinates[:2] != [site["longitude"], site["latitude"]]
                    or payload["header"]["time_standard"] != "UTC"):
                raise ValueError("site and archived weather coordinates/clock disagree")
    return profiles


def export_registry_csv(registry: dict, path: str | Path) -> None:
    # CSV is a readable evidence inventory, not the primary task deliverable.
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        names = ["parameter_id", "unit", "nominal", "sweep_values", "range_kind",
                 "evidence_status", "source_urls", "qaif_calibrated", "transfer_limit"]
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for entry in registry["parameters"]:
            writer.writerow({key: entry[key] for key in names if key not in {"sweep_values", "source_urls"}}
                            | {"sweep_values": json.dumps(entry["sweep_values"]),
                               "source_urls": " | ".join(registry["sources"][key]["url"] or "declared assumption/model"
                                                          for key in entry["source_ids"])})


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
