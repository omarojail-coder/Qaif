"""Refine an archived end-of-hour forcing grid without inventing measurements."""

from __future__ import annotations

import math
from dataclasses import replace

from .config import Config
from .model import Step, pipe_strains


def hold_refine(steps: list[Step], sample_period_s: int = 600) -> list[Step]:
    """Each archived row k>0 is held over its preceding interval.

    This is an offline piecewise-constant reconstruction. It cannot create
    sub-hourly source information or imply an online look-ahead measurement.
    """
    if (not isinstance(sample_period_s, int) or isinstance(sample_period_s, bool)
            or sample_period_s <= 0 or not steps or steps[0].timestamp_s != 0):
        raise ValueError("refinement requires positive integer period and a t=0 initialization")
    refined = [steps[0]]
    for before, after in zip(steps, steps[1:]):
        interval = after.timestamp_s - before.timestamp_s
        count = interval / sample_period_s
        if interval <= 0 or not count.is_integer():
            raise ValueError("sample period must divide every source interval exactly")
        for index in range(1, int(count) + 1):
            refined.append(replace(after, timestamp_s=before.timestamp_s + index * sample_period_s))
    return refined


def mechanical_stress_guard(config: Config, step: Step, steel_temperature_k: float,
                            stress_budget_pa: float) -> float:
    """Conservative elastic scope guard, not a grade-specific design check.

    Check both extremes around the pipe circumference, since a sensor might
    sit at a zero-bending azimuth while other locations carry larger stress.
    The restraint model's thermal stress is included. Shear is unmodeled.
    """
    if not math.isfinite(stress_budget_pa) or stress_budget_pa <= 0:
        raise ValueError("stress budget must be positive finite")
    hoop, axial, _, _ = pipe_strains(config, step, steel_temperature_k)
    thermal_axial = (-config.axial_restraint_fraction * config.young_modulus_pa
                     * config.expansion_per_k * (steel_temperature_k-config.reference_temperature_k))
    inertia = math.pi * (config.steel_outer_radius_m**4-config.inner_radius_m**4) / 4
    bending = abs(step.bending_moment_nm) * config.steel_outer_radius_m / inertia
    maximum = max(math.sqrt(hoop**2 + (axial+thermal_axial+sign*bending)**2
                            - hoop*(axial+thermal_axial+sign*bending)) for sign in (-1,1))
    if maximum > stress_budget_pa:
        raise ValueError("scenario exceeds the declared research elastic stress budget")
    return maximum
