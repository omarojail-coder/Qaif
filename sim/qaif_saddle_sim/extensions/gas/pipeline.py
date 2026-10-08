"""Causal coupling of unchanged discharge and sensor components."""

import math

from ._source.model import SourceConfig, LeakInput, discharge, number
from ._sensor.model import H2SConfig, H2SInput, H2SSensor


class CoupledGasSimulator:
    def __init__(self, source_config: SourceConfig, transport, sensor_config: H2SConfig,
                 seed: int, *, internal_step_s=0.05):
        source_config.validate()
        sensor_config.validate()
        number("internal_step_s", internal_step_s, positive=True)
        self.source_config = source_config
        self.transport = transport
        self.sensor = H2SSensor(sensor_config, seed)
        self.internal_step_s = internal_step_s
        if sensor_config.reference_temperature_k != transport.config.ambient_temperature_k:
            raise ValueError("sensor and transport reference temperatures must match")
        if sensor_config.reference_pressure_kpa * 1000 != transport.config.ambient_pressure_pa_abs:
            raise ValueError("sensor and transport reference pressures must match")
        self.last_timestamp_s = None

    def step(self, inputs: LeakInput, *, force_missing=False):
        inputs.validate()
        if type(force_missing) is not bool:
            raise ValueError("force_missing must be boolean")
        if inputs.ambient_pressure_pa_abs != self.transport.config.ambient_pressure_pa_abs:
            raise ValueError("transport reference pressure is fixed in this review")
        if self.last_timestamp_s is not None and inputs.timestamp_s <= self.last_timestamp_s:
            raise ValueError("timestamps must be strictly increasing")
        source = discharge(self.source_config, inputs)
        self.transport.validate_source(source)
        # Advance using previously supplied sources. The new source value is
        # applied only AFTER reaching its timestamp; future inputs never act
        # during the preceding interval.
        if self.last_timestamp_s is None:
            local = self.transport.advance_to(inputs.timestamp_s)
            observed, sensor_truth = self.sensor.step(H2SInput(inputs.timestamp_s, local, force_missing))
        else:
            start, end = self.last_timestamp_s, inputs.timestamp_s
            count = math.ceil((end - start) / self.internal_step_s)
            if count > 1_000_000:
                raise ValueError("interval too long for this review integrator")
            for i in range(1, count + 1):
                t = end if i == count else start + (end - start) * i / count
                local = self.transport.advance_to(t)
                observed, sensor_truth = self.sensor.step(H2SInput(t, local, force_missing and i == count))
        self.transport.set_source(inputs.timestamp_s, source)
        self.last_timestamp_s = inputs.timestamp_s
        truth = {**source, **sensor_truth, **self.transport.audit()}
        return observed, truth
