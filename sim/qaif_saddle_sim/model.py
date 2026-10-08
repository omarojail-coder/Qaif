"""Conservative lumped thermal model, thin-wall mechanics, and separate readout."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .config import Channel, Config

STEFAN_BOLTZMANN = 5.670374419e-8  # W m^-2 K^-4


@dataclass(frozen=True)
class Step:
    timestamp_s: float
    pressure_pa: float
    fluid_temperature_k: float
    ambient_temperature_k: float
    sky_temperature_k: float
    solar_w_m2: float
    solar_incidence: float
    h_inner_w_m2k: float
    h_outer_w_m2k: float
    wet_drive: float
    wet_path_open: bool
    drying_rate_multiplier: float
    bending_moment_nm: float
    bending_direction_rad: float
    hoop_coupling_multiplier: float
    axial_coupling_multiplier: float
    temperature_flatline: bool
    wetness_flatline: bool
    force_missing: bool
    event_type: str

    def validate(self) -> None:
        nonnegative = ("timestamp_s", "pressure_pa", "solar_w_m2", "h_inner_w_m2k",
                       "h_outer_w_m2k", "drying_rate_multiplier")
        positive = ("fluid_temperature_k", "ambient_temperature_k", "sky_temperature_k")
        for key in nonnegative:
            value = getattr(self, key)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be nonnegative and finite")
        for key in positive:
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
        if self.h_inner_w_m2k == 0 or self.h_outer_w_m2k == 0:
            raise ValueError("convection coefficients must be positive")
        for key in ("solar_incidence", "wet_drive", "hoop_coupling_multiplier",
                    "axial_coupling_multiplier"):
            value = getattr(self, key)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be in [0, 1]")
        for key in ("bending_moment_nm", "bending_direction_rad"):
            if not math.isfinite(getattr(self, key)):
                raise ValueError(f"{key} must be finite")
        if not self.event_type:
            raise ValueError("event_type is required as simulation-only metadata")


@dataclass
class State:
    steel_temperature_k: float
    coating_temperature_k: float
    wetness: float
    sensor_temperature_k: float
    sensor_wetness: float
    last_timestamp_s: float | None = None
    previous_noise: dict[str, float] = field(default_factory=dict)
    previous_observed: dict[str, float | None] = field(default_factory=dict)
    sensor_strain_microstrain: dict[str, float] = field(default_factory=dict)


def pipe_strains(config: Config, step: Step, steel_temperature_k: float) -> tuple[float, float, float, float]:
    """Return hoop/axial pressure stresses (Pa) and total strains (dimensionless).

    Thin-wall closed ends; uniform steel temperature and an idealized axial
    restraint fraction. The local bending moment is supplied at the saddle,
    not inferred from defect distance or support geometry.
    """
    r_i = config.inner_radius_m
    t = config.wall_thickness_m
    sigma_h = step.pressure_pa * r_i / t
    sigma_a = sigma_h / 2
    delta_t = steel_temperature_k - config.reference_temperature_k
    thermal_axial_stress = (
        -config.axial_restraint_fraction * config.young_modulus_pa
        * config.expansion_per_k * delta_t
    )
    e = config.young_modulus_pa
    nu = config.poisson_ratio
    eps_h = (sigma_h - nu * (sigma_a + thermal_axial_stress)) / e
    eps_h += config.expansion_per_k * delta_t
    eps_a = ((sigma_a + thermal_axial_stress) - nu * sigma_h) / e
    eps_a += config.expansion_per_k * delta_t
    r_o = config.steel_outer_radius_m
    inertia_m4 = math.pi * (r_o**4 - r_i**4) / 4
    bending_strain = (
        step.bending_moment_nm * r_o
        * math.cos(config.sensor_theta_rad - step.bending_direction_rad)
        / (e * inertia_m4)
    )
    eps_a += bending_strain
    eps_h -= nu * bending_strain
    return sigma_h, sigma_a, eps_h, eps_a


def thermal_parts(config: Config, step: Step) -> tuple[float, float, float, float, float, float]:
    """Return R_in, R_steel-coat, R_coat-surface, C_steel, C_coat, A_surface."""
    r_i = config.inner_radius_m
    r_o = config.steel_outer_radius_m
    r_c = config.coating_outer_radius_m
    # Equal-volume radial midpoints place each lumped node at its annular center.
    r_sm = math.sqrt((r_i * r_i + r_o * r_o) / 2)
    r_cm = math.sqrt((r_o * r_o + r_c * r_c) / 2)
    l = config.active_length_m
    phi = config.thermal_sector_angle_rad
    r_in = 1 / (step.h_inner_w_m2k * phi * r_i * l)
    r_in += math.log(r_sm / r_i) / (phi * config.steel.conductivity_w_mk * l)
    r_sc = math.log(r_o / r_sm) / (phi * config.steel.conductivity_w_mk * l)
    r_sc += math.log(r_cm / r_o) / (phi * config.coating.conductivity_w_mk * l)
    r_cs = math.log(r_c / r_cm) / (phi * config.coating.conductivity_w_mk * l)
    c_s = (
        config.steel.density_kg_m3 * config.steel.heat_capacity_j_kgk
        * (phi / 2) * (r_o * r_o - r_i * r_i) * l
    )
    c_c = (
        config.coating.density_kg_m3 * config.coating.heat_capacity_j_kgk
        * (phi / 2) * (r_c * r_c - r_o * r_o) * l
    )
    a_out = phi * r_c * l
    return r_in, r_sc, r_cs, c_s, c_c, a_out


def surface_temperature_k(config: Config, step: Step, coating_temperature_k: float,
                          r_cs: float, a_out: float) -> float:
    """Solve coating-surface heat balance by bisection, including sun and sky."""
    solar = config.solar_absorptivity * step.solar_w_m2 * step.solar_incidence

    def residual(temp_k: float) -> float:
        conduction = (coating_temperature_k - temp_k) / r_cs
        outer_flux = (
            step.h_outer_w_m2k * (temp_k - step.ambient_temperature_k)
            + config.emissivity * STEFAN_BOLTZMANN
            * (temp_k**4 - step.sky_temperature_k**4)
            - solar
        )
        return conduction - a_out * outer_flux

    low, high = 1.0, max(2000.0, coating_temperature_k + 1000.0)
    if residual(low) < 0 or residual(high) > 0:
        raise ValueError("surface heat balance has no root in the physical bracket")
    for _ in range(65):
        mid = (low + high) / 2
        if residual(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def advance_physics(config: Config, state: State, step: Step, dt_s: float) -> float:
    """Update thermal and local wetness states; return outer surface temperature.

    Explicit energy balances use automatically limited substeps, rather than
    presenting a forward Euler update as an implicit numerical method.
    """
    r_in, r_sc, r_cs, c_s, c_c, a_out = thermal_parts(config, step)
    if dt_s:
        tau_s = c_s / (1 / r_in + 1 / r_sc)
        tau_c = c_c / (1 / r_sc + 1 / r_cs)
        max_substep = 0.1 * min(tau_s, tau_c)
        count = math.ceil(dt_s / max_substep)
        if count > 100_000:
            raise ValueError("time interval too long for explicit thermal solver")
        sub_dt = dt_s / count
        for _ in range(count):
            surface_k = surface_temperature_k(config, step, state.coating_temperature_k, r_cs, a_out)
            q_in = (step.fluid_temperature_k - state.steel_temperature_k) / r_in
            q_sc = (state.steel_temperature_k - state.coating_temperature_k) / r_sc
            q_out = (state.coating_temperature_k - surface_k) / r_cs
            next_steel = state.steel_temperature_k + sub_dt * (q_in - q_sc) / c_s
            next_coat = state.coating_temperature_k + sub_dt * (q_sc - q_out) / c_c
            if next_steel <= 0 or next_coat <= 0:
                raise ValueError("thermal integration produced nonphysical temperature")
            state.steel_temperature_k = next_steel
            state.coating_temperature_k = next_coat

        ingress = config.wet_ingress_rate_per_s * step.wet_drive if step.wet_path_open else 0.0
        drying = config.wet_drying_rate_per_s * step.drying_rate_multiplier
        total = ingress + drying
        if total:
            equilibrium = ingress / total
            state.wetness = equilibrium + (state.wetness - equilibrium) * math.exp(-total * dt_s)
            state.wetness = min(1.0, max(0.0, state.wetness))
    return surface_temperature_k(config, step, state.coating_temperature_k, r_cs, a_out)


def _lag(current: float, target: float, tau_s: float, dt_s: float) -> float:
    if tau_s == 0:
        return target
    return current + (target - current) * (-math.expm1(-dt_s / tau_s))


class Simulator:
    def __init__(self, config: Config, seed: int, *, physics_cache=None, mechanical_response=None):
        config.validate()
        self.config = config
        self.rng = random.Random(seed)
        self.physics_cache = physics_cache
        self.mechanical_response = mechanical_response
        self.state = State(
            steel_temperature_k=config.initial_steel_temperature_k,
            coating_temperature_k=config.initial_coating_temperature_k,
            wetness=config.initial_wetness,
            sensor_temperature_k=config.initial_sensor_temperature_k,
            sensor_wetness=config.initial_sensor_wetness,
        )

    def _noise(self, name: str, channel: Channel) -> float:
        previous = self.state.previous_noise.get(name, 0.0)
        value = (
            channel.noise_ar1 * previous
            + channel.noise_std * math.sqrt(1 - channel.noise_ar1**2) * self.rng.gauss(0, 1)
        )
        self.state.previous_noise[name] = value
        return value

    def step(self, inputs: Step) -> tuple[dict[str, object], dict[str, object]]:
        inputs.validate()
        old_t = self.state.last_timestamp_s
        if old_t is not None and inputs.timestamp_s <= old_t:
            raise ValueError("timestamps must be strictly increasing")
        dt_s = 0.0 if old_t is None else inputs.timestamp_s - old_t
        surface_k = (advance_physics(self.config, self.state, inputs, dt_s)
                     if self.physics_cache is None else
                     self.physics_cache.advance(self.config, self.state, inputs, dt_s))
        strain_model = self.mechanical_response or pipe_strains
        sigma_h, sigma_a, eps_h, eps_a = strain_model(
            self.config, inputs, self.state.steel_temperature_k
        )
        self.state.sensor_temperature_k = _lag(
            self.state.sensor_temperature_k, surface_k, self.config.temperature.lag_s, dt_s
        )
        self.state.sensor_wetness = _lag(
            self.state.sensor_wetness, self.state.wetness, self.config.wetness.lag_s, dt_s
        )
        delta_surface = surface_k - self.config.reference_temperature_k

        def strain_reading(name: str, channel: Channel, multiplier: float) -> float:
            angle = channel.orientation_from_hoop_rad
            directed = eps_h * math.cos(angle)**2 + eps_a * math.sin(angle)**2
            target = directed * 1e6 * channel.gain * multiplier
            previous = self.state.sensor_strain_microstrain.get(name, target)
            transferred = _lag(previous, target, channel.lag_s, dt_s)
            self.state.sensor_strain_microstrain[name] = transferred
            return (
                transferred
                + channel.temperature_cross_per_k * delta_surface
                + channel.bias + channel.drift_per_s * inputs.timestamp_s
                + self._noise(name, channel)
            )

        observed = {
            "timestamp_s": inputs.timestamp_s,
            "strain_hoop_microstrain": strain_reading(
                "hoop", self.config.strain_hoop, inputs.hoop_coupling_multiplier
            ),
            "strain_axial_microstrain": strain_reading(
                "axial", self.config.strain_axial, inputs.axial_coupling_multiplier
            ),
            "temperature_k": (
                self.config.reference_temperature_k
                + (self.state.sensor_temperature_k - self.config.reference_temperature_k)
                * self.config.temperature.gain
                + self.config.temperature.bias
                + self.config.temperature.drift_per_s * inputs.timestamp_s
                + self._noise("temperature", self.config.temperature)
            ),
            "wetness_index": (
                self.state.sensor_wetness * self.config.wetness.gain
                + self.config.wetness.bias
                + self.config.wetness.drift_per_s * inputs.timestamp_s
                + self._noise("wetness", self.config.wetness)
            ),
        }
        observed["wetness_index"] = min(1.0, max(0.0, observed["wetness_index"]))
        if inputs.temperature_flatline and "temperature_k" in self.state.previous_observed:
            observed["temperature_k"] = self.state.previous_observed["temperature_k"]
        if inputs.wetness_flatline and "wetness_index" in self.state.previous_observed:
            observed["wetness_index"] = self.state.previous_observed["wetness_index"]
        # Consume the same stochastic schedule in both branches, including a
        # forced outage. Short-circuiting this draw used to change subsequent
        # measurement noise even after a packet-loss intervention had ended.
        random_missing = self.rng.random() < self.config.packet_loss_probability
        missing = inputs.force_missing or random_missing
        observed["packet_valid"] = not missing
        if missing:
            for key in ("strain_hoop_microstrain", "strain_axial_microstrain", "temperature_k", "wetness_index"):
                observed[key] = None
        else:
            self.state.previous_observed = {
                key: observed[key] for key in
                ("strain_hoop_microstrain", "strain_axial_microstrain", "temperature_k", "wetness_index")
            }
        latent = {
            "timestamp_s": inputs.timestamp_s,
            "asset_id": self.config.asset_id,
            "run_id": self.config.run_id,
            "source_episode_id": self.config.source_episode_id,
            "event_type": inputs.event_type,
            "steel_temperature_k": self.state.steel_temperature_k,
            "coating_temperature_k": self.state.coating_temperature_k,
            "coating_surface_temperature_k": surface_k,
            "wetness_true": self.state.wetness,
            "pressure_hoop_stress_pa": sigma_h,
            "pressure_axial_stress_pa": sigma_a,
            "strain_hoop_microstrain_true": eps_h * 1e6,
            "strain_axial_microstrain_true": eps_a * 1e6,
            "hoop_coupling_multiplier": inputs.hoop_coupling_multiplier,
            "axial_coupling_multiplier": inputs.axial_coupling_multiplier,
            "wet_path_open": inputs.wet_path_open,
        }
        self.state.last_timestamp_s = inputs.timestamp_s
        return observed, latent
