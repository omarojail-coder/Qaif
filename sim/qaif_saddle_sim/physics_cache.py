"""Bounded exact-state reuse for repeated physics in a matched research study."""
from .model import advance_physics


class PhysicsCache:
    def __init__(self,max_entries=50_000):
        if not isinstance(max_entries,int) or isinstance(max_entries,bool) or max_entries<1:
            raise ValueError("cache size must be a positive integer")
        self.max_entries=max_entries;self.values={};self.hits=0;self.misses=0

    def advance(self,config,state,step,dt_s):
        # All fields read by advance_physics/thermal_parts/surface balance.
        # No rounding, interpolation, noise, readout, or mutable sensor state.
        key=(config.inner_diameter_m,config.wall_thickness_m,config.coating_thickness_m,
             config.active_length_m,config.thermal_sector_angle_rad,config.steel,config.coating,
             config.solar_absorptivity,config.emissivity,config.wet_ingress_rate_per_s,config.wet_drying_rate_per_s,
             state.steel_temperature_k,state.coating_temperature_k,state.wetness,dt_s,
             step.fluid_temperature_k,step.ambient_temperature_k,step.sky_temperature_k,step.solar_w_m2,
             step.solar_incidence,step.h_inner_w_m2k,step.h_outer_w_m2k,step.wet_drive,
             step.wet_path_open,step.drying_rate_multiplier)
        if key in self.values:
            self.hits+=1
            steel,coat,wet,surface=self.values[key]
            state.steel_temperature_k=steel;state.coating_temperature_k=coat;state.wetness=wet
            return surface
        self.misses+=1
        surface=advance_physics(config,state,step,dt_s)
        if len(self.values)>=self.max_entries:
            self.values.pop(next(iter(self.values)))
        self.values[key]=(state.steel_temperature_k,state.coating_temperature_k,state.wetness,surface)
        return surface

    def summary(self):
        return {"method":"bounded exact-state physics memoization; sensor/noise state never reused",
                "max_entries":self.max_entries,"stored_entries":len(self.values),"hits":self.hits,"misses":self.misses}
