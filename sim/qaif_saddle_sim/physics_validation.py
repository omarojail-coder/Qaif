"""Independent analytical/numerical references; never a field calibration."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

from .config import Config
from .io import read_forcing
from .model import State, advance_physics, pipe_strains, _lag

MIT_URL = "https://web.mit.edu/course/3/3.11/www/modules/pv.pdf"
LAME_URL = "https://www.osti.gov/servlets/purl/1133475"


def _reference_network(c, step):
    # Derived directly from cylindrical Fourier conduction and annular volume.
    # None of the production thermal/surface helper functions is called here.
    a, b, d = c.inner_diameter_m/2, c.inner_diameter_m/2+c.wall_thickness_m, c.coating_outer_radius_m
    steel_node, coat_node = math.sqrt((a*a+b*b)/2), math.sqrt((b*b+d*d)/2)
    sector_length = c.thermal_sector_angle_rad*c.active_length_m
    conductances = (
        1/(1/(step.h_inner_w_m2k*a*sector_length)+math.log(steel_node/a)/(c.steel.conductivity_w_mk*sector_length)),
        1/(math.log(b/steel_node)/(c.steel.conductivity_w_mk*sector_length)+math.log(coat_node/b)/(c.coating.conductivity_w_mk*sector_length)),
        c.coating.conductivity_w_mk*sector_length/math.log(d/coat_node),
    )
    capacities = (c.steel.density_kg_m3*c.steel.heat_capacity_j_kgk*(b*b-a*a)*sector_length/2,
                  c.coating.density_kg_m3*c.coating.heat_capacity_j_kgk*(d*d-b*b)*sector_length/2)
    return conductances, capacities, d*sector_length


def exact_linear_thermal(c, step, initial, elapsed):
    """Exact 2x2 matrix exponential, with emissivity and solar set to zero."""
    if c.emissivity != 0 or step.solar_w_m2 != 0:
        raise ValueError("linear reference requires zero radiation and solar input")
    (gi, gx, gs), (cs, cc), area = _reference_network(c, step)
    go = step.h_outer_w_m2k*area
    surface_effective = gs*go/(gs+go)
    heat = (step.fluid_temperature_k-step.ambient_temperature_k)/(1/gi+1/gx+1/surface_effective)
    equilibrium = (step.fluid_temperature_k-heat/gi, step.ambient_temperature_k+heat/surface_effective)
    aa, bb, dd, ee = -(gi+gx)/cs, gx/cs, gx/cc, -(gx+surface_effective)/cc
    discr = math.sqrt((aa-ee)**2+4*bb*dd)
    fast, slow = (aa+ee-discr)/2, (aa+ee+discr)/2
    ef, es = math.exp(fast*elapsed), math.exp(slow*elapsed)
    m00 = ((aa-fast)*es-(aa-slow)*ef)/discr
    m01 = bb*(es-ef)/discr
    m10 = dd*(es-ef)/discr
    m11 = ((ee-fast)*es-(ee-slow)*ef)/discr
    x, y = initial[0]-equilibrium[0], initial[1]-equilibrium[1]
    return equilibrium[0]+m00*x+m01*y, equilibrium[1]+m10*x+m11*y


def nonlinear_thermal_reference(c, step, initial, elapsed, max_step=0.5):
    """Separate small-step RK4 and Newton surface balance; no production solver."""
    (gi, gx, gs), (cs, cc), area = _reference_network(c, step)
    radiation = 5.670374419e-8*c.emissivity*area
    outer = step.h_outer_w_m2k*area
    solar = c.solar_absorptivity*step.solar_w_m2*step.solar_incidence*area

    def rhs(y):
        steel, coat = y
        surface = (gs*coat+outer*step.ambient_temperature_k+solar)/(gs+outer)
        for _ in range(20):
            residual = gs*(coat-surface)-outer*(surface-step.ambient_temperature_k)-radiation*(surface**4-step.sky_temperature_k**4)+solar
            increment = residual/(gs+outer+4*radiation*surface**3)
            surface += increment
            if abs(increment) < 1e-11:
                break
        else:
            raise ValueError("reference surface Newton solve did not converge")
        return ((gi*(step.fluid_temperature_k-steel)-gx*(steel-coat))/cs,
                (gx*(steel-coat)-gs*(coat-surface))/cc)

    interval = min(max_step, 0.02*min(cs/(gi+gx), cc/(gx+gs)))
    count = max(1, math.ceil(elapsed/interval))
    if count > 500_000:
        raise ValueError("reference integration exceeds declared step cap")
    h = elapsed/count
    y = tuple(initial)
    for _ in range(count):
        k1 = rhs(y)
        k2 = rhs(tuple(v+h*k/2 for v,k in zip(y,k1)))
        k3 = rhs(tuple(v+h*k/2 for v,k in zip(y,k2)))
        k4 = rhs(tuple(v+h*k for v,k in zip(y,k3)))
        y = tuple(v+h*(a+2*b+2*d+e)/6 for v,a,b,d,e in zip(y,k1,k2,k3,k4))
    return y


def validate_physics(config, step):
    mechanics=[]
    for diameter in (0.508, 0.9):
        for thickness in (0.01,0.015,0.02):
            c = replace(config,inner_diameter_m=diameter,wall_thickness_m=thickness,axial_restraint_fraction=0)
            c.validate()
            for pressure in (1e6,3e6,6e6):
                loading=replace(step,pressure_pa=pressure,bending_moment_nm=0)
                sh,sa,eh,ea=pipe_strains(c,loading,c.reference_temperature_k)
                # Lamé exact outer-surface stresses for capped, homogeneous,
                # elastic cylinders, external gauge pressure zero.
                ratio=c.inner_radius_m**2/(c.steel_outer_radius_m**2-c.inner_radius_m**2)
                exact_h,exact_a=2*pressure*ratio,pressure*ratio
                exact_eh=(exact_h-c.poisson_ratio*exact_a)/c.young_modulus_pa
                error=abs(eh-exact_eh)/abs(exact_eh)
                # The theoretical thin-wall relative outer-surface error is t/D.
                if error > thickness/diameter+1e-10 or error >= .05:
                    raise ValueError("thin-wall approximation exceeds its analytic scope bound")
                mechanics.append({"diameter_m":diameter,"wall_m":thickness,"pressure_pa":pressure,
                                  "relative_outer_hoop_strain_error":error})
    bending=[]
    for moment in (-8000,0,2000,8000):
        c=replace(config,axial_restraint_fraction=0)
        loading=replace(step,pressure_pa=0,bending_moment_nm=moment,bending_direction_rad=0)
        _,_,eh,ea=pipe_strains(c,loading,c.reference_temperature_k)
        residual=abs(eh+c.poisson_ratio*ea)
        if residual>1e-12:
            raise ValueError("bending violates isotropic Poisson coupling")
        bending.append({"moment_nm":moment,"constitutive_residual":residual})
    thermal=[]
    linear=replace(config,emissivity=0)
    loading=replace(step,fluid_temperature_k=320,ambient_temperature_k=290,sky_temperature_k=290,
                    solar_w_m2=0,h_inner_w_m2k=20,h_outer_w_m2k=8,wet_drive=0)
    for elapsed in (60,600,3600):
        initial=(290,290)
        expected=exact_linear_thermal(linear,loading,initial,elapsed)
        state=State(*initial,0,290,0)
        advance_physics(linear,state,loading,elapsed)
        error=max(abs(a-b) for a,b in zip(expected,(state.steel_temperature_k,state.coating_temperature_k)))
        if error>.25:
            raise ValueError("thermal integration differs by >0.25 K from exact linear reference")
        thermal.append({"reference":"exact_linear_matrix_exponential","duration_s":elapsed,"max_error_k":error})
    for solar in (0,900):
        nonlinear=replace(loading,solar_w_m2=solar,sky_temperature_k=270)
        expected=nonlinear_thermal_reference(config,nonlinear,(290,290),600)
        refined=nonlinear_thermal_reference(config,nonlinear,(290,290),600,max_step=.25)
        convergence=max(abs(a-b) for a,b in zip(expected,refined))
        state=State(290,290,0,290,0)
        advance_physics(config,state,nonlinear,600)
        error=max(abs(a-b) for a,b in zip(refined,(state.steel_temperature_k,state.coating_temperature_k)))
        if convergence>1e-4 or error>.25:
            raise ValueError("nonlinear thermal reference convergence/production tolerance failed")
        thermal.append({"reference":"independent_RK4_Newton","solar_w_m2":solar,
                        "duration_s":600,"step_halving_error_k":convergence,"max_error_k":error})
    tau=300
    lag_errors=[abs(_lag(0,1,tau,t)-(1-math.exp(-t/tau))) for t in (0,30,300,3000)]
    if max(lag_errors)>1e-12:
        raise ValueError("constant-target readout lag differs from analytic solution")
    return {"schema_version":"1","scope":"equation and solver verification, not sensor/field validation",
            "mechanical_references":[MIT_URL,LAME_URL],"mechanics":mechanics,"bending":bending,
            "thermal":thermal,"constant_target_lag_max_error":max(lag_errors),
            "numerical_tolerance_k":.25,"numerical_tolerance_basis":"declared software verification bound; no detection/calibration meaning",
            "passed":True,"field_validated":False,"training_ready":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",required=True)
    parser.add_argument("--forcing",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    report=validate_physics(Config.from_json(args.config),read_forcing(args.forcing)[0])
    path=Path(args.out); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"field_validated":False,"training_ready":False}))


if __name__=="__main__": main()
