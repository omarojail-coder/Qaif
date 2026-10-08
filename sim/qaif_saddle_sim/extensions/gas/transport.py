"""Two explicit, uncalibrated transport assumptions for numerical review.

Open air: passive scalar in a prescribed uniform tangential velocity field,
constant effective diffusivity, point source on a reflecting flat surface.
This does NOT solve gas-jet momentum, buoyancy, pipe wakes, or wind at 10 m.

Under patch: an illustrative well-mixed, vented sensing gap at fixed pressure
and temperature, with a specified capture fraction and ambient sweep. It does
NOT predict real mounting paths, capture efficiency or sealed-cavity pressure.
"""

import math
from dataclasses import dataclass

from ._source.model import R_UNIVERSAL_J_MOL_K, number


def environment(temperature_k, pressure_pa_abs, background_ppm):
    number("temperature_k", temperature_k, positive=True)
    number("pressure_pa_abs", pressure_pa_abs, positive=True)
    number("background_h2s_ppm", background_ppm, nonnegative=True)
    if temperature_k != 293.15:
        raise ValueError("current sensor stage is limited to a fixed 20 C environment")
    if not 80000 <= pressure_pa_abs <= 120000 or background_ppm > 200:
        raise ValueError("reference pressure or H2S background outside review bounds")


def source_rates(source):
    total = source["mixture_molar_flow_mol_s_true"]
    h2s = source["h2s_molar_flow_mol_s_true"]
    number("mixture molar source", total, nonnegative=True)
    number("H2S molar source", h2s, nonnegative=True)
    if h2s > total:
        raise ValueError("H2S molar source cannot exceed total mixture source")


@dataclass(frozen=True)
class OpenAirConfig:
    receiver_x_m: float
    receiver_y_m: float
    sensor_height_m: float
    wind_x_m_s: float
    wind_y_m_s: float
    effective_diffusivity_m2_s: float
    ambient_temperature_k: float = 293.15
    ambient_pressure_pa_abs: float = 101325.0
    background_h2s_ppm: float = 0.0
    assumption_basis: str = "prescribed_local_flow_research"

    def validate(self):
        for key in ("receiver_x_m", "receiver_y_m", "wind_x_m_s", "wind_y_m_s"):
            number(key, getattr(self, key))
        number("sensor_height_m", self.sensor_height_m, positive=True)
        if self.sensor_height_m > 0.03:
            raise ValueError("this review limits the sensing height to 3 cm above the flat surface")
        number("effective_diffusivity_m2_s", self.effective_diffusivity_m2_s, positive=True)
        offset = math.hypot(self.receiver_x_m, self.receiver_y_m)
        if not 0.2 - 1e-12 <= offset <= 0.3 + 1e-12:
            raise ValueError("this open-air review is restricted to 20..30 cm surface offsets")
        if self.assumption_basis != "prescribed_local_flow_research":
            raise ValueError("local flow and diffusivity are research assumptions")
        environment(self.ambient_temperature_k, self.ambient_pressure_pa_abs, self.background_h2s_ppm)


def arrival_fraction(age_s, radius_m, speed_m_s, diffusivity_m2_s):
    """Normalized step response of the 3D constant-coefficient Green function.

    F(t)=0.5[erfc(a)+exp(U*r/D)*erfc(b)], with a=(r-Ut)/sqrt(4Dt),
    b=(r+Ut)/sqrt(4Dt). For large b, cancellation gives exp(-a*a)
    times the erfc asymptotic prefactor, avoiding exp overflow/underflow.
    """
    if age_s <= 0:
        return 0.0
    root = math.sqrt(4 * diffusivity_m2_s * age_s)
    a = (radius_m - speed_m_s * age_s) / root
    b = (radius_m + speed_m_s * age_s) / root
    if b >= 20:
        term, series = 1.0, 1.0
        for n in range(1, 11):
            term *= -(2 * n - 1) / (2 * b * b)
            series += term
        tail = math.exp(-a * a) * series / (math.sqrt(math.pi) * b)
    else:
        tail = math.exp(speed_m_s * radius_m / diffusivity_m2_s) * math.erfc(b)
    result = (math.erfc(a) + tail) / 2
    if not math.isfinite(result) or not -1e-12 <= result <= 1 + 1e-12:
        raise ValueError("invalid transport arrival fraction")
    return min(1.0, max(0.0, result))


class OpenAirTransport:
    def __init__(self, config: OpenAirConfig):
        config.validate()
        self.config = config
        self.radius = math.sqrt(config.receiver_x_m**2 + config.receiver_y_m**2 + config.sensor_height_m**2)
        self.speed = math.hypot(config.wind_x_m_s, config.wind_y_m_s)
        dot = config.wind_x_m_s * config.receiver_x_m + config.wind_y_m_s * config.receiver_y_m
        diffusivity = config.effective_diffusivity_m2_s
        # Factor 2 is the image source at the reflecting surface z=0;
        # normal velocity is zero. Ambient concentration is added separately.
        self.steady_gain_s_m3 = 2 * math.exp((dot - self.speed * self.radius) / (2 * diffusivity)) / (4 * math.pi * diffusivity * self.radius)
        self.ambient_molar_density = config.ambient_pressure_pa_abs / (R_UNIVERSAL_J_MOL_K * config.ambient_temperature_k)
        self.events = []  # timestamp, change in H2S molar source strength
        self.current_h2s_molar_source = 0.0
        self.time_s = None
        self.local_ppm = config.background_h2s_ppm

    def validate_source(self, source):
        source_rates(source)
        # Explicit dilute-tracer guard. This is a mathematical approximation
        # threshold, NOT an empirical jet-validity or detection criterion.
        fraction = source["mixture_molar_flow_mol_s_true"] * self.steady_gain_s_m3 / self.ambient_molar_density
        if fraction > 0.01:
            raise ValueError("point-source tracer approximation exceeds 1% carrier fraction; use another flow model")
        maximum_ppm = self.config.background_h2s_ppm + source["h2s_molar_flow_mol_s_true"] * self.steady_gain_s_m3 / self.ambient_molar_density * 1e6
        if maximum_ppm > 200:
            raise ValueError("local H2S may exceed the sensor prototype's 200 ppm bound")

    def advance_to(self, time_s):
        number("time_s", time_s, nonnegative=True)
        if self.time_s is not None and time_s < self.time_s:
            raise ValueError("transport time cannot run backwards")
        concentration_mol_m3 = math.fsum(delta * self.steady_gain_s_m3 * arrival_fraction(
            time_s - start, self.radius, self.speed, self.config.effective_diffusivity_m2_s)
            for start, delta in self.events)
        if concentration_mol_m3 < -1e-14:
            raise ValueError("negative source contribution produced by transport history")
        self.local_ppm = self.config.background_h2s_ppm + max(0.0, concentration_mol_m3) / self.ambient_molar_density * 1e6
        self.time_s = time_s
        return self.local_ppm

    def set_source(self, time_s, source):
        self.validate_source(source)
        if self.time_s != time_s:
            raise ValueError("advance to the source timestamp before applying its new value")
        q = source["h2s_molar_flow_mol_s_true"]
        delta = q - self.current_h2s_molar_source
        if delta:
            self.events.append((time_s, delta))
        self.current_h2s_molar_source = q

    def audit(self):
        return {"local_h2s_ppm_true": self.local_ppm,
                "transport_assumption_true": self.config.assumption_basis,
                "source_to_sensor_distance_m_true": self.radius,
                "source_history_changes_true": len(self.events)}


@dataclass(frozen=True)
class GapConfig:
    sensing_volume_m3: float
    ambient_sweep_m3_s: float
    source_capture_fraction: float
    ambient_temperature_k: float = 293.15
    ambient_pressure_pa_abs: float = 101325.0
    background_h2s_ppm: float = 0.0
    assumption_basis: str = "illustrative_open_vented_sensing_gap"

    def validate(self):
        number("sensing_volume_m3", self.sensing_volume_m3, positive=True)
        number("ambient_sweep_m3_s", self.ambient_sweep_m3_s, positive=True)
        number("source_capture_fraction", self.source_capture_fraction, nonnegative=True)
        if self.source_capture_fraction > 1:
            raise ValueError("source_capture_fraction must be <=1")
        if self.assumption_basis != "illustrative_open_vented_sensing_gap":
            raise ValueError("gap geometry and capture are illustrative assumptions")
        environment(self.ambient_temperature_k, self.ambient_pressure_pa_abs, self.background_h2s_ppm)


class GapTransport:
    def __init__(self, config: GapConfig):
        config.validate()
        self.config = config
        self.density_mol_m3 = config.ambient_pressure_pa_abs / (R_UNIVERSAL_J_MOL_K * config.ambient_temperature_k)
        self.inventory_mol = self.density_mol_m3 * config.sensing_volume_m3
        self.ambient_flow_mol_s = self.density_mol_m3 * config.ambient_sweep_m3_s
        self.source_flow_mol_s = self.h2s_flow_mol_s = 0.0
        self.local_ppm = config.background_h2s_ppm
        self.time_s = None
        self.h2s_in_mol = self.h2s_out_mol = 0.0

    def validate_source(self, source):
        source_rates(source)
        captured_total = source["mixture_molar_flow_mol_s_true"] * self.config.source_capture_fraction
        captured_h2s = source["h2s_molar_flow_mol_s_true"] * self.config.source_capture_fraction
        maximum_ppm = (captured_h2s + self.ambient_flow_mol_s * self.config.background_h2s_ppm / 1e6) / (captured_total + self.ambient_flow_mol_s) * 1e6
        if maximum_ppm > 200:
            raise ValueError("local gap concentration may exceed the sensor prototype's 200 ppm bound")

    def advance_to(self, time_s):
        number("time_s", time_s, nonnegative=True)
        if self.time_s is not None and time_s < self.time_s:
            raise ValueError("transport time cannot run backwards")
        dt = 0.0 if self.time_s is None else time_s - self.time_s
        total_flow = self.ambient_flow_mol_s + self.source_flow_mol_s
        inlet_h2s = self.h2s_flow_mol_s + self.ambient_flow_mol_s * self.config.background_h2s_ppm / 1e6
        equilibrium = inlet_h2s / total_flow
        rate = total_flow / self.inventory_mol
        initial = self.local_ppm / 1e6
        relax = -math.expm1(-rate * dt)
        final = initial + (equilibrium - initial) * relax
        integral_fraction = equilibrium * dt + (initial - equilibrium) * relax / rate
        self.h2s_in_mol += inlet_h2s * dt
        self.h2s_out_mol += total_flow * integral_fraction
        self.local_ppm = final * 1e6
        self.time_s = time_s
        return self.local_ppm

    def set_source(self, time_s, source):
        self.validate_source(source)
        if self.time_s != time_s:
            raise ValueError("advance to the source timestamp before applying its new value")
        self.source_flow_mol_s = source["mixture_molar_flow_mol_s_true"] * self.config.source_capture_fraction
        self.h2s_flow_mol_s = source["h2s_molar_flow_mol_s_true"] * self.config.source_capture_fraction

    def audit(self):
        accumulated = self.inventory_mol * (self.local_ppm - self.config.background_h2s_ppm) / 1e6
        return {"local_h2s_ppm_true": self.local_ppm,
                "transport_assumption_true": self.config.assumption_basis,
                "gap_h2s_in_mol_true": self.h2s_in_mol,
                "gap_h2s_out_mol_true": self.h2s_out_mol,
                "gap_h2s_accumulation_mol_true": accumulated,
                "gap_h2s_balance_residual_mol_true": self.h2s_in_mol - self.h2s_out_mol - accumulated}
