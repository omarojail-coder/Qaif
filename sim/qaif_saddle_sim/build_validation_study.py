"""Two-source research expansion, independent solver references and coherence QA."""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import asdict,replace
from pathlib import Path

from . import __version__
from .additional_sources import load_extra_asset,load_native_hourly_archive
from .coherence_audit import audit_study,plan_source_split
from .config import Config
from .evidence_registry import sha256
from .experiment import export_pair,_write_steps
from .io import read_forcing,simulate_to_directory
from .model import Step
from .physics_validation import validate_physics
from .physics_cache import PhysicsCache
from .reference_episode import (prepare_reference_episode,_weather_rows,_checked_file,
    _internal_h,_external_h,_local_pressure,R_UNIVERSAL)
from .replay_grid import hold_refine
from .study_audit import audit_pair
from .timeline import build_timeline

ROOT=Path(__file__).resolve().parent


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")


def prepare_extra(weather_key,out,hours=72):
    sources=ROOT/"reference_data"; additional=sources/"additional_v1"
    inventory=json.loads((sources/"source_manifest.json").read_text(encoding="utf-8"))["entries"]
    weather_path=_checked_file(sources,inventory[weather_key]);weather,units=_weather_rows(weather_path)
    weather=weather[:hours]
    if len(weather)!=hours: raise ValueError("additional weather window unavailable")
    asset=load_extra_asset(additional)
    native,profile=load_native_hourly_archive(additional,"2002-01-01 00:00",hours)
    data=json.loads((ROOT/"examples/reference_template_config.json").read_text(encoding="utf-8"))
    identity=weather_key+"_gaslibe39_sanbruno_72h"
    data.update(asset_id=asset["asset_id"],run_id=identity,source_episode_id=identity,
                inner_diameter_m=asset["inner_diameter_m"],reference_temperature_k=asset["gas_temperature_k"],
                initial_steel_temperature_k=asset["gas_temperature_k"],initial_coating_temperature_k=asset["gas_temperature_k"],
                initial_sensor_temperature_k=asset["gas_temperature_k"],parameter_basis="research_sweep")
    save(out/"config.json",data); config=Config.from_json(out/"config.json")
    gas=json.loads((ROOT/"examples/reference_gas_assumptions.json").read_text(encoding="utf-8"))
    # New archive has geometry/gas, but no transient initial state. All flow,
    # inlet anchoring and horizontal-location choices are explicitly assumed.
    assumed={"upstream_absolute_pressure_pa":3.5e6,"mass_flow_kg_s":2.0,
             "hydraulic_exposure_length_m":asset["pipe_length_m"]/2,
             "upstream_pressure_basis":"interior research point in 25-50 bar benchmark bounds, absolute convention assumed",
             "mass_flow_basis":"declared 2 kg/s research operating point; not a solved nomination or measurement",
             "hydraulic_location_basis":"half pipe length; horizontal single-pipe surrogate",
             "gas_transport_parameters":gas}
    hi,reynolds,friction=_internal_h(2.0,asset["inner_diameter_m"],asset["roughness_m"],
                                     gas["heat_capacity_j_kgk"],gas["viscosity_pa_s"],gas["thermal_conductivity_w_mk"])
    steps=[]; diagnostics=[]
    for i in range(hours+1):
        j=max(0,i-1); hour=weather[j]; inlet=3.5e6*native[j]["upstream_pressure_ratio"]
        if not asset["source_pressure_min_pa"]<=inlet<=asset["source_pressure_max_pa"]:
            raise ValueError("additional inlet surrogate outside benchmark envelope")
        absolute=_local_pressure(inlet,2.0,asset["inner_diameter_m"],assumed["hydraulic_exposure_length_m"],
                                 friction,gas["compressibility_factor"],R_UNIVERSAL/asset["molar_mass_kg_mol"],asset["gas_temperature_k"])
        if absolute<=gas["external_pressure_pa"]: raise ValueError("nonpositive additional gauge pressure")
        step=Step(i*3600,absolute-gas["external_pressure_pa"],asset["gas_temperature_k"],
                  hour["T2M"]+273.15,(hour["ALLSKY_SFC_LW_DWN"]/5.670374419e-8)**.25,
                  hour["ALLSKY_SFC_SW_DWN"],gas["solar_incidence_factor"],hi,
                  _external_h(hour["WS10M"],2*config.coating_outer_radius_m,gas["wind_height_factor"]),
                  min(1,hour["PRECTOTCORR"]/gas["wet_drive_mm_h_at_one"]),False,1.0,0,0,1,1,False,False,False,"normal_environment")
        step.validate();steps.append(step)
        diagnostics.append({"timestamp_s":i*3600,"weather_utc_hour":"initialization" if i==0 else hour["utc_hour"],
                            "pressure_source_local_hour":native[j]["source_local_hour"],
                            "upstream_pressure_ratio":native[j]["upstream_pressure_ratio"],
                            "surrogate_upstream_absolute_pressure_pa":inlet,"surrogate_absolute_pressure_pa":absolute,
                            "mass_flow_kg_s":2,"reynolds":reynolds,"friction":friction})
    _write_steps(out/"forcing.csv",steps)
    for name,values in (("pressure_hourly_snapshot.csv",native),("source_diagnostics.csv",diagnostics)):
        with (out/name).open("w",encoding="utf-8",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    save(out/"assumptions.json",assumed)
    reference={"schema_version":"2","episode_id":identity,"sample_count":hours+1,"weather_interval_count":hours,
               "sample_period_s":3600,"weather_source_key":weather_key,"power_units":units,
               "gaslib_properties":asset,"pressure_profile":profile,"assumptions":assumed,
               "source_files":{"weather":inventory[weather_key],"additional_archive":{"sha256":sha256(additional/"source_manifest.json")}},
               "quality_summary":{"all_source_hashes_verified":True},
               "limits":["GasLibE-39 is artificial stationary geometry, not a real pipeline or a transient solution.",
                         "Native historical pressure ratios are transferred to an assumed inlet absolute pressure; no source pressure unit conversion.",
                         "Gas temperature is the benchmark reference; mass flow is assumed constant.",
                         "Weather and source pressures are different places/years, paired by elapsed hours.",
                         "Wall, coating, transfer and support parameters remain assumptions."],
               "training_ready":False,
               "output_sha256":{name:sha256(out/name) for name in ("config.json","forcing.csv","pressure_hourly_snapshot.csv","source_diagnostics.csv","assumptions.json")}}
    save(out/"reference_manifest.json",reference)
    return reference


def spec_for(config,site,family,mechanism,start,duration,changes,period,final,case=False):
    spec={"schema_version":"1","asset_id":config.asset_id,"site_id":site,"base_episode_id":config.source_episode_id,
          "scenario_family_id":family,"mechanism_id":mechanism,"evidence_level":"declared_research_grid",
          "unknown_assumptions":["No calibrated saddle transfer; no measured incident amplitudes.",
                                  "Profiles evaluated on end-sample timestamps and held over intervals; no continuous-time event claim."],
          "phases":[{"phase_id":"intervention","event_type":mechanism,"start_s":start+period,"end_s":start+duration+period,"changes":changes},
                    {"phase_id":"recovery","event_type":"normal_environment","start_s":start+duration+period,"end_s":final+period,"changes":{}}]}
    if case:spec["inspired_by_case_id"]="QC-02"
    return spec


def build(output_dir):
    out=Path(output_dir)
    if out.exists() and any(out.iterdir()):raise FileExistsError("nonempty study output")
    out.mkdir(parents=True,exist_ok=True)
    period=600; budget=200e6; records=[];physics=[];physics_cache=PhysicsCache()
    profiles={"nominal":{"seed":42,"overrides":{}},
              "reduced_transfer_noisier":{"seed":173,"overrides":{"packet_loss_probability":.02,
                    "strain_hoop":{"gain":.4,"lag_s":600,"noise_std":2},
                    "strain_axial":{"gain":.4,"lag_s":600,"noise_std":2},"temperature":{"lag_s":600,"noise_std":.5}}}}
    save(out/"sensor_profiles.json",{"basis":"parameter registry research grid, not sampled calibration distribution","profiles":profiles,"training_ready":False})
    for name in ("parameter_registry.json","profiles.json"):
        shutil.copyfile(ROOT/"evidence"/name,out/("previous_"+name))
    for name in ("source_manifest.json","GasLibE-39.net","san_bruno_pressure.csv"):
        destination=out/"additional_source_snapshots"/name;destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT/"reference_data/additional_v1"/name,destination)
    bases=[("coast_rain","red_sea_coast_rain_2024","primary"),
           ("coast_summer","red_sea_coast_summer_2024","primary"),
           ("inland_winter","inland_desert_winter_2024","extra"),
           ("coast_winter","red_sea_coast_winter_2024","extra")]
    for base_id,weather_key,kind in bases:
        base=out/"bases"/base_id
        if kind=="primary":
            inventory=json.loads((ROOT/"reference_data/source_manifest.json").read_text(encoding="utf-8"))["entries"]
            weather,_=_weather_rows(_checked_file(ROOT/"reference_data",inventory[weather_key]))
            reference=prepare_reference_episode(ROOT/"reference_data",weather_key,ROOT/"examples/reference_template_config.json",base,
                ROOT/"examples/reference_gas_assumptions.json",window_start_utc=weather[48]["utc_hour"],window_hours=72,
                pressure_mode="ntsb_relative_upstream",ntsb_pressure_dir=ROOT.parent/"outputs/ntsb_pressure_audit_v1/west_spill_1067220",
                ntsb_start_local="2025-09-13 15:00")
            tokens=["asset:p_br52","benchmark:"+reference["source_files"]["gaslib_network"]["sha256"],
                    "flow:"+reference["source_files"]["trr_boundary"]["sha256"],
                    "pressure:"+reference["pressure_profile"]["source_group_id"],
                    "weather:"+reference["source_files"][weather_key]["sha256"]]
        else:
            reference=prepare_extra(weather_key,base)
            tokens=["asset:gaslibe39_P_NW_1","benchmark:"+reference["gaslib_properties"]["network_sha256"],
                    "pressure:"+reference["pressure_profile"]["source_group_id"],
                    "weather:"+reference["source_files"]["weather"]["sha256"]]
        config=Config.from_json(base/"config.json");steps=hold_refine(read_forcing(base/"forcing.csv"),period)
        validation=validate_physics(config,steps[0]);save(base/"physics_validation.json",validation);physics.append(validation)
        starts=[18*3600,30*3600]
        rain=base_id=="coast_rain"
        if rain:
            wet=[s.timestamp_s-period for s in steps if s.timestamp_s>=12*3600 and s.wet_drive>0]
            starts=[wet[0],next(t for t in wet if t>=wet[0]+6*3600)]
        for profile_id,settings in profiles.items():
            data=asdict(config)
            for key,value in settings["overrides"].items():
                if isinstance(value,dict):data[key].update(value)
                else:data[key]=value
            profile_path=out/"profile_configs"/base_id/(profile_id+".json");save(profile_path,data)
            configured=Config.from_json(profile_path)
            for slot,start in enumerate(starts):
                duration=(6 if slot==0 else 12)*3600; schedule="early" if slot==0 else "late"
                bending=({"mode":"linear","from":0,"to":2000} if slot==0 else {"mode":"pulse","base":0,"peak":-8000,"peak_fraction":.5})
                plans=[("bending","mechanical_change",{"bending_moment_nm":bending}),
                       ("coupling","sensor_fault",{"hoop_coupling_multiplier":{"mode":"linear","from":1,"to":.7 if slot==0 else .4},
                                                      "axial_coupling_multiplier":{"mode":"linear","from":1,"to":.7 if slot==0 else .4}}),
                       ("packet_gap","sensor_fault",{"force_missing":{"mode":"hold","value":True}}),
                       ("temperature_flatline","sensor_fault",{"temperature_flatline":{"mode":"hold","value":True}})]
                if rain:plans.append(("wet_path","interface_wetting",{"wet_path_open":{"mode":"hold","value":True}}))
                if rain and slot==0 and profile_id=="nominal":
                    plans.append(("wet_path_case_QC02","interface_wetting",{"wet_path_open":{"mode":"hold","value":True}}))
                for family,mechanism,changes in plans:
                    spec=spec_for(configured,base_id,family,mechanism,start,duration,changes,period,steps[-1].timestamp_s,case=family.endswith("case_QC02"))
                    event,labels,counts,case=build_timeline(configured,steps,spec)
                    pair=out/"scenarios"/base_id/profile_id/(schedule+"_"+family)
                    export_pair(configured,steps,event,pair,settings["seed"],spec,mechanism,sum(counts.values()),case,
                        split_group="pending",spec_filename="timeline_spec.json",reference_provenance=reference,physics_cache=physics_cache,
                        extra_manifest={"base_id":base_id,"physical_window_start_s":start,"physical_window_end_s":start+duration,
                            "reference_provenance_scope":"parent hourly source before hold refinement","simulation_period_s":period,
                            "source_sample_period_s":3600,"sensor_profile_id":profile_id})
                    with (pair/"inputs/timeline_samples.csv").open("w",encoding="utf-8",newline="") as handle:
                        writer=csv.DictWriter(handle,fieldnames=list(labels[0]));writer.writeheader();writer.writerows(labels)
                    manifest_path=pair/"paired_manifest.json";manifest=json.loads(manifest_path.read_text())
                    manifest["timeline_samples_sha256"]=sha256(pair/"inputs/timeline_samples.csv");save(manifest_path,manifest)
                    audit=audit_pair(pair,start,period,budget,mechanism);save(pair/"audit.json",audit)
                    record={"record_id":base_id+":"+profile_id+":"+schedule+":"+family,"pair_dir":str(pair.relative_to(out)),
                            "base_id":base_id,"weather_key":weather_key,"asset_id":configured.asset_id,
                            "sensor_profile_id":profile_id,"schedule_id":schedule,"family":family,"mechanism":mechanism,
                            "physical_start_s":start,"duration_s":duration,"source_tokens":tokens,"audit":audit}
                    records.append(record)
                    if len(records)%8==0: print(json.dumps({"completed_pairs":len(records)}),flush=True)
    plan=plan_source_split(records)
    group_by_id={r:group["group_id"] for group in plan["groups"] for r in group["record_ids"]}
    for record in records:
        record["source_group_id"]=group_by_id[record["record_id"]]
        path=out/record["pair_dir"]/"paired_manifest.json";meta=json.loads(path.read_text())
        meta.update(split_group=record["source_group_id"],source_tokens=record["source_tokens"]);save(path,meta)
    coherence=audit_study(out,records);save(out/"coherence_audit.json",coherence)
    generic=out/"scenarios/coast_rain/nominal/early_wet_path"
    inspired=out/"scenarios/coast_rain/nominal/early_wet_path_case_QC02"
    case_identical=all((generic/branch/name).read_bytes()==(inspired/branch/name).read_bytes() for branch in ("control","intervention") for name in ("observed.csv","context.csv"))
    if not case_identical:raise ValueError("case provenance left a signal fingerprint")
    save(out/"calibration_status.json",{"status":"waiting_for_independent_measurements","field_validated":False,
        "equation_solver_references_passed":True,"needed":["same-point independent hoop/axial strain and surface temperature traces",
            "known pipe/material/coating/adhesive and sensor mounting","sensor wetness conversion and lag measurements"],"training_ready":False})
    summary={"schema_version":"1","generator_version":__version__,"scenario_pair_count":len(records),"simulation_run_count":2*len(records),
        "base_count":len(bases),"asset_count":2,"independent_pressure_source_count":2,"source_component_count":len(plan["groups"]),
        "simulation_period_s":period,"window_hours":72,"rows_per_run":433,"sensor_profile_count":len(profiles),
        "solver_execution":physics_cache.summary(),
        "case_vs_generic_byte_identical":case_identical,"equation_solver_validation_passed":True,
        "pre_event_balanced_accuracy":coherence["pre_event_diagnostic"].get("balanced_accuracy"),
        "context_only_balanced_accuracy":coherence["signal_removed_context_only_diagnostic"].get("balanced_accuracy"),
        "train_validation_test_created":False,"field_validated":False,"training_ready":False,"pairs":records,
        "remaining_gates":["at least a third disjoint source component for three-way evaluation",
                           "independent measurements of saddle transfer/temperature/wetness",
                           "sufficient near-threshold coverage and separate alarm-model evaluation after data readiness"]}
    save(out/"summary.json",summary);save(out/"source_groups.json",plan)
    save(out/"files_sha256.json",{str(p.relative_to(out)):sha256(p) for p in sorted(out.rglob("*")) if p.is_file()})
    print(json.dumps({k:summary[k] for k in ("scenario_pair_count","simulation_run_count","source_component_count","training_ready")}),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",required=True);args=parser.parse_args();build(args.out)


if __name__=="__main__":main()
