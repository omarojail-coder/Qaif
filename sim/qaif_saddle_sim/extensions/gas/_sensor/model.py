"""Numeric electrochemical readout under declared fixed reference conditions.

The manufacturer supplies specification bounds, not the dynamics/calibration
of a Qaif device. First-order kinetics, recovery, electronics and calibration
below are configurable research assumptions. No concentration transport or
environmental compensation is implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, fields
from pathlib import Path


def _number(name: str, value: object, *, minimum=None, positive=False) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class H2SConfig:
    parameter_basis: str = "research_assumptions"
    rise_t90_s: float = 45.0
    recovery_t90_s: float = 90.0
    physical_sensitivity_na_per_ppm: float = 2000.0
    calibration_sensitivity_na_per_ppm: float = 2000.0
    zero_current_na: float = -50.0
    calibration_zero_current_na: float = -50.0
    drift_na_per_s: float = 0.0
    noise_std_ppm: float = 0.0005
    noise_correlation_s: float = 0.0
    readout_upper_limit_ppm: float = 100.0
    initial_response_ppm: float = 0.0
    packet_loss_probability: float = 0.0
    reference_temperature_k: float = 293.15
    reference_humidity_percent: float = 50.0
    reference_pressure_kpa: float = 101.325

    def validate(self) -> None:
        if self.parameter_basis != "research_assumptions":
            raise ValueError("this prototype only supports research_assumptions")
        for f in fields(self):
            if f.name != "parameter_basis":
                _number(f.name, getattr(self, f.name))
        for key in ("rise_t90_s", "recovery_t90_s", "physical_sensitivity_na_per_ppm",
                    "calibration_sensitivity_na_per_ppm", "readout_upper_limit_ppm"):
            _number(key, getattr(self, key), positive=True)
        for key in ("noise_std_ppm", "noise_correlation_s", "initial_response_ppm"):
            _number(key, getattr(self, key), minimum=0)
        if not 0 <= self.packet_loss_probability <= 1:
            raise ValueError("packet_loss_probability must be in [0, 1]")
        if not 1450 <= self.physical_sensitivity_na_per_ppm <= 2600:
            raise ValueError("physical sensitivity must remain in the selected reference bounds")
        if not -300 <= self.zero_current_na <= 200:
            raise ValueError("zero current must remain in the selected reference bounds")
        if self.initial_response_ppm > 200 or self.readout_upper_limit_ppm > 100:
            raise ValueError("initial response <=200 ppm; readout ceiling <=100 ppm")
        if self.reference_temperature_k != 293.15:
            raise ValueError("phase 1 is restricted to a fixed 20 C sensor environment")
        if not 15 <= self.reference_humidity_percent <= 90:
            raise ValueError("reference humidity must be within 15..90 percent")
        if not 80 <= self.reference_pressure_kpa <= 120:
            raise ValueError("reference pressure must be within 80..120 kPa")

    @classmethod
    def from_json(cls, path: str | Path) -> "H2SConfig":
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = {f.name for f in fields(cls)}
        if not isinstance(values, dict) or set(values) != expected:
            raise ValueError("H2S config must contain exactly all declared fields")
        config = cls(**values)
        config.validate()
        return config


@dataclass(frozen=True)
class H2SInput:
    timestamp_s: float
    local_h2s_ppm: float
    force_missing: bool = False

    def validate(self) -> None:
        _number("timestamp_s", self.timestamp_s, minimum=0)
        _number("local_h2s_ppm", self.local_h2s_ppm, minimum=0)
        if self.local_h2s_ppm > 200:
            raise ValueError("input >200 ppm is outside this prototype; damage is unmodelled")
        if type(self.force_missing) is not bool:
            raise ValueError("force_missing must be a boolean")


@dataclass
class H2SState:
    response_ppm: float
    last_timestamp_s: float | None = None
    first_timestamp_s: float | None = None
    held_concentration_ppm: float = 0.0
    noise_ppm: float = 0.0


def _stream(seed: int, purpose: str) -> random.Random:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    digest = hashlib.sha256(f"qaif-h2s-v1:{purpose}:{seed}".encode("ascii")).digest()
    return random.Random(int.from_bytes(digest, "big"))


class H2SSensor:
    """Concentrations are left-held: input at t applies on [t, next_t).

    This prevents the future concentration sample from affecting earlier
    dynamics. The first timestamp reports the explicit initial response;
    it does not silently equilibrate to the first input concentration.
    """

    def __init__(self, config: H2SConfig, seed: int):
        config.validate()
        self.config = config
        self.noise_rng = _stream(seed, "measurement_noise")
        self.loss_rng = _stream(seed, "packet_loss")
        self.state = H2SState(config.initial_response_ppm)

    def validate_next(self, inputs: H2SInput) -> None:
        inputs.validate()
        if self.state.last_timestamp_s is not None:
            if inputs.timestamp_s <= self.state.last_timestamp_s:
                raise ValueError("H2S timestamps must be strictly increasing")

    def step(self, inputs: H2SInput, *, shared_packet_missing: bool = False):
        self.validate_next(inputs)
        if type(shared_packet_missing) is not bool:
            raise ValueError("shared_packet_missing must be a boolean")
        c, s = self.config, self.state
        first = s.last_timestamp_s is None
        dt = 0.0 if first else inputs.timestamp_s - s.last_timestamp_s
        start = inputs.timestamp_s if first else s.first_timestamp_s
        target = s.held_concentration_ppm
        t90 = c.rise_t90_s if target >= s.response_ppm else c.recovery_t90_s
        # Exact solution for a constant target, independent of solver substeps.
        s.response_ppm += (target - s.response_ppm) * (-math.expm1(-dt * math.log(10) / t90))
        z = self.noise_rng.gauss(0.0, 1.0)
        if first or c.noise_correlation_s == 0:
            s.noise_ppm = c.noise_std_ppm * z
        else:
            retention = math.exp(-dt / c.noise_correlation_s)
            s.noise_ppm = (retention * s.noise_ppm
                           + c.noise_std_ppm * math.sqrt(-math.expm1(-2 * dt / c.noise_correlation_s)) * z)
        current = (c.physical_sensitivity_na_per_ppm * s.response_ppm
                   + c.zero_current_na + c.drift_na_per_s * (inputs.timestamp_s - start))
        raw_ppm = ((current - c.calibration_zero_current_na)
                   / c.calibration_sensitivity_na_per_ppm + s.noise_ppm)
        if not math.isfinite(raw_ppm) or not math.isfinite(current):
            raise ValueError("configuration produced a nonfinite readout")
        # Always consume the dropout draw; forcing a missing packet never
        # changes future sensor noise, packet draws or the physical response.
        random_missing = self.loss_rng.random() < c.packet_loss_probability
        missing = inputs.force_missing or shared_packet_missing or random_missing
        limited = raw_ppm >= c.readout_upper_limit_ppm
        observed = {
            "timestamp_s": inputs.timestamp_s,
            "h2s_ppm": None if missing else min(raw_ppm, c.readout_upper_limit_ppm),
            "h2s_valid": not missing and not limited,
            "h2s_status": "missing" if missing else "readout_limit" if limited else "ok",
        }
        # Signed near-zero readings are intentional: baseline/calibration noise
        # is not converted into an artificial positive concentration floor.
        truth = {
            "timestamp_s": inputs.timestamp_s,
            "local_h2s_ppm_true": inputs.local_h2s_ppm,
            "sensor_response_ppm_true": s.response_ppm,
            "electrode_current_na_true": current,
            "noise_ppm": s.noise_ppm,
            "unlimited_readout_ppm": raw_ppm,
        }
        s.first_timestamp_s = start
        s.last_timestamp_s = inputs.timestamp_s
        s.held_concentration_ppm = inputs.local_h2s_ppm
        return observed, truth
