"""Explicit simulator parameters. No field-calibration constants are embedded here."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


def _finite_positive(name: str, value: float, *, allow_zero: bool = False) -> None:
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'} and finite")


def _fraction(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class Material:
    density_kg_m3: float
    heat_capacity_j_kgk: float
    conductivity_w_mk: float

    def validate(self, name: str) -> None:
        for key, value in vars(self).items():
            _finite_positive(f"{name}.{key}", value)


@dataclass(frozen=True)
class Channel:
    gain: float
    lag_s: float
    bias: float
    drift_per_s: float
    noise_std: float
    noise_ar1: float
    temperature_cross_per_k: float = 0.0
    orientation_from_hoop_rad: float = 0.0

    def validate(self, name: str) -> None:
        if not math.isfinite(self.gain) or self.gain < 0:
            raise ValueError(f"{name}.gain must be nonnegative and finite")
        _finite_positive(f"{name}.lag_s", self.lag_s, allow_zero=True)
        _finite_positive(f"{name}.noise_std", self.noise_std, allow_zero=True)
        if not -1 < self.noise_ar1 < 1:
            raise ValueError(f"{name}.noise_ar1 must be in (-1, 1)")
        for key in ("bias", "drift_per_s", "temperature_cross_per_k", "orientation_from_hoop_rad"):
            if not math.isfinite(getattr(self, key)):
                raise ValueError(f"{name}.{key} must be finite")


@dataclass(frozen=True)
class Config:
    asset_id: str
    run_id: str
    source_episode_id: str
    parameter_basis: str
    reference_temperature_k: float
    inner_diameter_m: float
    wall_thickness_m: float
    coating_thickness_m: float
    active_length_m: float
    thermal_sector_angle_rad: float
    sensor_theta_rad: float
    young_modulus_pa: float
    poisson_ratio: float
    expansion_per_k: float
    axial_restraint_fraction: float
    steel: Material
    coating: Material
    solar_absorptivity: float
    emissivity: float
    wet_ingress_rate_per_s: float
    wet_drying_rate_per_s: float
    initial_steel_temperature_k: float
    initial_coating_temperature_k: float
    initial_sensor_temperature_k: float
    initial_wetness: float
    initial_sensor_wetness: float
    strain_hoop: Channel
    strain_axial: Channel
    temperature: Channel
    wetness: Channel
    packet_loss_probability: float
    observable_context: tuple[str, ...]

    @classmethod
    def from_json(cls, path: str | Path) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["steel"] = Material(**data["steel"])
        data["coating"] = Material(**data["coating"])
        for key in ("strain_hoop", "strain_axial", "temperature", "wetness"):
            data[key] = Channel(**data[key])
        data["observable_context"] = tuple(data["observable_context"])
        config = cls(**data)
        config.validate()
        return config

    def validate(self) -> None:
        for key in ("asset_id", "run_id", "source_episode_id"):
            if not getattr(self, key):
                raise ValueError(f"{key} is required")
        if self.parameter_basis not in {"test_fixture", "research_sweep"}:
            raise ValueError("parameter_basis must be test_fixture or research_sweep")
        for key in (
            "reference_temperature_k", "inner_diameter_m", "wall_thickness_m",
            "active_length_m", "young_modulus_pa", "initial_steel_temperature_k",
            "initial_coating_temperature_k", "initial_sensor_temperature_k",
        ):
            _finite_positive(key, getattr(self, key))
        _finite_positive("coating_thickness_m", self.coating_thickness_m)
        if (not math.isfinite(self.thermal_sector_angle_rad)
                or not 0 < self.thermal_sector_angle_rad <= 2 * math.pi):
            raise ValueError("thermal_sector_angle_rad must be in (0, 2*pi]")
        for key in ("wet_ingress_rate_per_s", "wet_drying_rate_per_s"):
            _finite_positive(key, getattr(self, key), allow_zero=True)
        if self.inner_diameter_m / self.wall_thickness_m <= 20:
            raise ValueError("thin-wall model requires inner_diameter_m / wall_thickness_m > 20")
        if not 0 < self.poisson_ratio < 0.5:
            raise ValueError("poisson_ratio must be in (0, 0.5)")
        _finite_positive("expansion_per_k", self.expansion_per_k, allow_zero=True)
        if not math.isfinite(self.sensor_theta_rad):
            raise ValueError("sensor_theta_rad must be finite")
        for key in ("axial_restraint_fraction", "solar_absorptivity", "emissivity",
                    "initial_wetness", "initial_sensor_wetness", "packet_loss_probability"):
            _fraction(key, getattr(self, key))
        self.steel.validate("steel")
        self.coating.validate("coating")
        for key in ("strain_hoop", "strain_axial", "temperature", "wetness"):
            getattr(self, key).validate(key)
        allowed = {"pressure_pa", "fluid_temperature_k", "ambient_temperature_k",
                   "solar_w_m2", "solar_incidence"}
        if len(self.observable_context) != len(set(self.observable_context)):
            raise ValueError("observable_context has duplicate fields")
        if set(self.observable_context) - allowed:
            raise ValueError(f"observable_context must be a subset of {sorted(allowed)}")

    @property
    def inner_radius_m(self) -> float:
        return self.inner_diameter_m / 2

    @property
    def steel_outer_radius_m(self) -> float:
        return self.inner_radius_m + self.wall_thickness_m

    @property
    def coating_outer_radius_m(self) -> float:
        return self.steel_outer_radius_m + self.coating_thickness_m
