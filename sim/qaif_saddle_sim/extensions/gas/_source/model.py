"""Quasi-steady ideal-gas orifice discharge, with explicit H2S composition.

Uses reservoir/stagnation absolute pressure and temperature. No pipeline
depletion, real-gas equation of state, crack flow resistance, jet/plume mixing,
or concentration at a sensor is computed here. Discharge coefficient and
constant heat-capacity ratio are declared research parameters.
"""

import math
from dataclasses import dataclass

R_UNIVERSAL_J_MOL_K = 8.31446261815324
H2S_MOLAR_MASS_KG_MOL = 0.034081  # NIST WebBook: 34.081 g/mol
METHANE_MOLAR_MASS_KG_MOL = 0.0160425  # NIST WebBook: 16.0425 g/mol


def number(name, value, *, nonnegative=False, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if nonnegative and value < 0 or positive and value <= 0:
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")


def absolute_pressure(pressure_pa: float, *, convention: str, ambient_pressure_pa_abs: float) -> float:
    """Require an explicit convention; a gauge reading cannot be used silently."""
    number("pressure_pa", pressure_pa, nonnegative=True)
    number("ambient_pressure_pa_abs", ambient_pressure_pa_abs, positive=True)
    if convention == "absolute":
        result = pressure_pa
    elif convention == "gauge":
        result = pressure_pa + ambient_pressure_pa_abs
    else:
        raise ValueError("pressure convention must be exactly absolute or gauge")
    number("absolute pressure", result, positive=True)
    return result


def circular_hole_area(diameter_m: float) -> float:
    number("diameter_m", diameter_m, nonnegative=True)
    area = math.pi * (diameter_m / 2) ** 2
    number("hole area", area, nonnegative=True)
    return area


@dataclass(frozen=True)
class GasComposition:
    h2s_mole_fraction: float
    carrier_molar_mass_kg_mol: float
    heat_capacity_ratio: float

    def validate(self):
        number("h2s_mole_fraction", self.h2s_mole_fraction, nonnegative=True)
        if self.h2s_mole_fraction > 1:
            raise ValueError("h2s_mole_fraction must be <=1, not ppm or mass fraction")
        number("carrier_molar_mass_kg_mol", self.carrier_molar_mass_kg_mol, positive=True)
        number("heat_capacity_ratio", self.heat_capacity_ratio)
        if not 1 < self.heat_capacity_ratio <= 1.67:
            raise ValueError("heat_capacity_ratio must be in (1, 1.67] for this prototype")

    @property
    def mixture_molar_mass_kg_mol(self):
        return ((1 - self.h2s_mole_fraction) * self.carrier_molar_mass_kg_mol
                + self.h2s_mole_fraction * H2S_MOLAR_MASS_KG_MOL)


@dataclass(frozen=True)
class SourceConfig:
    composition: GasComposition
    discharge_coefficient: float
    parameter_basis: str = "ideal_gas_research_assumptions"
    fluid_phase: str = "single_phase_gas"

    def validate(self):
        if not isinstance(self.composition, GasComposition):
            raise ValueError("composition must be a GasComposition")
        self.composition.validate()
        number("discharge_coefficient", self.discharge_coefficient, positive=True)
        if self.discharge_coefficient > 1:
            raise ValueError("discharge_coefficient must be <=1")
        if self.parameter_basis != "ideal_gas_research_assumptions":
            raise ValueError("this component is a research ideal-gas approximation")
        if self.fluid_phase != "single_phase_gas":
            raise ValueError("liquid and multiphase releases are unsupported")


@dataclass(frozen=True)
class LeakInput:
    timestamp_s: float
    upstream_total_pressure_pa_abs: float
    upstream_total_temperature_k: float
    ambient_pressure_pa_abs: float
    opening_area_m2: float

    def validate(self):
        for name in ("timestamp_s", "opening_area_m2"):
            number(name, getattr(self, name), nonnegative=True)
        for name in ("upstream_total_pressure_pa_abs", "upstream_total_temperature_k", "ambient_pressure_pa_abs"):
            number(name, getattr(self, name), positive=True)


def discharge(config: SourceConfig, inputs: LeakInput) -> dict:
    """Return source TRUTH only. H2S ppm here describes the released mixture.

    It is never a concentration reading at the saddle. The subsonic pressure-
    ratio expression is algebraically derived from NASA's isentropic relations;
    the choked expression is the Mach=1 mass-flow equation. Cd scales ideal flow.
    """
    config.validate()
    inputs.validate()
    gas = config.composition
    gamma = gas.heat_capacity_ratio
    molar_mass = gas.mixture_molar_mass_kg_mol
    gas_constant = R_UNIVERSAL_J_MOL_K / molar_mass
    p0 = inputs.upstream_total_pressure_pa_abs
    ratio = inputs.ambient_pressure_pa_abs / p0
    critical_ratio = math.exp(gamma / (gamma - 1) * math.log(2 / (gamma + 1)))
    coefficient = (config.discharge_coefficient * inputs.opening_area_m2 * p0
                   / math.sqrt(gas_constant * inputs.upstream_total_temperature_k))
    if inputs.opening_area_m2 == 0:
        flow, regime = 0.0, "closed_opening"
    elif ratio >= 1:
        # This component computes outward flow only; it does not model ingress.
        flow, regime = 0.0, "no_outward_pressure_difference"
    elif ratio <= critical_ratio:
        flow = coefficient * math.sqrt(gamma) * (2 / (gamma + 1)) ** ((gamma + 1) / (2 * (gamma - 1)))
        regime = "choked"
    else:
        # Stable even when backpressure approaches upstream pressure. Avoid
        # subtracting nearly equal powers of the pressure ratio.
        log_ratio = math.log(ratio)
        power_difference = math.exp(2 / gamma * log_ratio) * (-math.expm1((gamma - 1) / gamma * log_ratio))
        flow = coefficient * math.sqrt(2 * gamma / (gamma - 1) * power_difference)
        regime = "subsonic"
    number("computed mass flow", flow, nonnegative=True)
    mixture_molar_flow = flow / molar_mass
    h2s_molar_flow = mixture_molar_flow * gas.h2s_mole_fraction
    h2s_mass_flow = h2s_molar_flow * H2S_MOLAR_MASS_KG_MOL
    for name, value in (("molar flow", mixture_molar_flow), ("H2S mass flow", h2s_mass_flow)):
        number(name, value, nonnegative=True)
    return {
        "timestamp_s": inputs.timestamp_s,
        "mixture_mass_flow_kg_s_true": flow,
        "mixture_molar_flow_mol_s_true": mixture_molar_flow,
        "h2s_mass_flow_kg_s_true": h2s_mass_flow,
        "h2s_molar_flow_mol_s_true": h2s_molar_flow,
        "released_mixture_h2s_ppm_true": gas.h2s_mole_fraction * 1e6,
        "mixture_molar_mass_kg_mol_true": molar_mass,
        "backpressure_ratio_true": ratio,
        "critical_backpressure_ratio_true": critical_ratio,
        "discharge_regime_true": regime,
    }


def source_trace(config: SourceConfig, inputs: list[LeakInput]) -> list[dict]:
    if not inputs:
        raise ValueError("source trace must not be empty")
    result = []
    last = -1.0
    for step in inputs:
        step.validate()
        if step.timestamp_s <= last:
            raise ValueError("timestamps must be strictly increasing")
        result.append(discharge(config, step))
        last = step.timestamp_s
    return result
