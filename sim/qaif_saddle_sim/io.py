"""Strict forcing ingestion and reproducible, separated simulation exports."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import fields
from pathlib import Path

from .config import Config
from .model import Simulator, Step
from . import __version__

BOOL_FIELDS = {"wet_path_open", "temperature_flatline", "wetness_flatline", "force_missing"}
TEXT_FIELDS = {"event_type"}


def read_forcing(path: str | Path) -> list[Step]:
    path = Path(path)
    expected = [field.name for field in fields(Step)]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if (reader.fieldnames is None or len(reader.fieldnames) != len(expected)
                or set(reader.fieldnames) != set(expected)):
            raise ValueError(f"forcing headers must exactly match: {', '.join(expected)}")
        steps: list[Step] = []
        previous_time = -1.0
        for line_number, row in enumerate(reader, start=2):
            try:
                if None in row or any(value is None or value == "" for value in row.values()):
                    raise ValueError("missing or extra cell")
                values = {}
                for key in expected:
                    value = row[key].strip()
                    if key in BOOL_FIELDS:
                        if value not in {"0", "1"}:
                            raise ValueError(f"{key} must be 0 or 1")
                        values[key] = value == "1"
                    elif key in TEXT_FIELDS:
                        values[key] = value
                    else:
                        values[key] = float(value)
                step = Step(**values)
                step.validate()
                if step.timestamp_s <= previous_time:
                    raise ValueError("timestamps must be strictly increasing")
                previous_time = step.timestamp_s
                steps.append(step)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"forcing line {line_number}: {exc}") from exc
    if not steps:
        raise ValueError("forcing file must contain at least one step")
    return steps


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reference_provenance(config_path: str | Path,
                              forcing_path: str | Path) -> dict | None:
    """Verify a prepared reference episode before propagating its provenance."""
    config_path, forcing_path = Path(config_path), Path(forcing_path)
    manifest_path = forcing_path.parent / "reference_manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("output_sha256", {})
    if (_sha256(config_path) != expected.get("config.json")
            or _sha256(forcing_path) != expected.get("forcing.csv")):
        raise ValueError("prepared reference config/forcing differs from its manifest")
    return manifest


def simulate_to_directory(config_path: str | Path, forcing_path: str | Path,
                          output_dir: str | Path, seed: int, *, physics_cache=None) -> dict[str, object]:
    config_path = Path(config_path)
    forcing_path = Path(forcing_path)
    output_dir = Path(output_dir)
    config = Config.from_json(config_path)
    steps = read_forcing(forcing_path)
    reference = load_reference_provenance(config_path, forcing_path)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    sim = Simulator(config, seed, physics_cache=physics_cache)
    observed_rows: list[dict[str, object]] = []
    latent_rows: list[dict[str, object]] = []
    context_rows: list[dict[str, object]] = []
    for step in steps:
        observed, latent = sim.step(step)
        observed_rows.append(observed)
        latent_rows.append(latent)
        context_rows.append({
            "timestamp_s": step.timestamp_s,
            **{key: getattr(step, key) for key in config.observable_context},
        })

    shutil.copyfile(config_path, output_dir / "config_snapshot.json")
    shutil.copyfile(forcing_path, output_dir / "forcing_snapshot.csv")
    if reference is not None:
        (output_dir / "reference_manifest_snapshot.json").write_text(
            json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    _write_csv(output_dir / "observed.csv", observed_rows)
    _write_csv(output_dir / "latent.csv", latent_rows)
    _write_csv(output_dir / "context.csv", context_rows)
    manifest: dict[str, object] = {
        "schema_version": "2",
        "generator_version": __version__,
        "asset_id": config.asset_id,
        "run_id": config.run_id,
        "source_episode_id": config.source_episode_id,
        "parameter_basis": config.parameter_basis,
        "seed": seed,
        "sample_count": len(steps),
        "config_sha256": _sha256(config_path),
        "forcing_sha256": _sha256(forcing_path),
        "reference_manifest_sha256": (
            _sha256(output_dir / "reference_manifest_snapshot.json")
            if reference is not None else None
        ),
        "observable_context": list(config.observable_context),
        "training_ready": False,
        "output_files": {
            name: _sha256(output_dir / name)
            for name in ("observed.csv", "context.csv", "latent.csv",
                         "config_snapshot.json", "forcing_snapshot.csv")
        },
        "limits": [
            "No measured saddle transfer function or calibration",
            "No inferred detection radius, leak, crack, wall-loss or scratch class",
            "Forcing event_type and latent.csv are excluded from model features",
            "Asset and run identifiers are kept in manifests, not observed/context columns",
        ],
    }
    if reference is not None:
        manifest["output_files"]["reference_manifest_snapshot.json"] = (
            _sha256(output_dir / "reference_manifest_snapshot.json")
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest
