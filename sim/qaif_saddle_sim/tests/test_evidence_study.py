"""Evidence coverage, time semantics, stress scope and group-leakage guards."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qaif_saddle_sim.config import Config
from qaif_saddle_sim.evidence_registry import load_registry, validate_profiles, validate_nominals
from qaif_saddle_sim.io import read_forcing, simulate_to_directory
from qaif_saddle_sim.replay_grid import hold_refine, mechanical_stress_guard
from qaif_saddle_sim.study_audit import audit_run, connected_groups, validate_split_assignment
from qaif_saddle_sim.build_evidence_study import _timeline
from qaif_saddle_sim.timeline import build_timeline
from qaif_saddle_sim.model import Simulator

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=ROOT/"evidence/parameter_registry.json"
TEMPLATE=ROOT/"examples/reference_template_config.json"
GAS=ROOT/"examples/reference_gas_assumptions.json"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.template=json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.gas=json.loads(GAS.read_text(encoding="utf-8"))

    def test_registry_covers_implicit_defaults_and_declared_grids(self):
        registry=load_registry(REGISTRY,self.template,self.gas)
        ids={e["parameter_id"] for e in registry["parameters"]}
        self.assertEqual(len(ids),72)
        self.assertIn("config.temperature.orientation_from_hoop_rad",ids)
        self.assertIn("config.wetness.temperature_cross_per_k",ids)
        self.assertTrue(all(not e["qaif_calibrated"] for e in registry["parameters"]))
        effective=json.loads(json.dumps(self.template))
        effective["inner_diameter_m"]=.508
        for key in ("reference_temperature_k","initial_steel_temperature_k",
                    "initial_coating_temperature_k","initial_sensor_temperature_k"):
            effective[key]=289.15
        validate_nominals(registry,effective,self.gas)
        effective["strain_hoop"]["gain"]=.95
        with self.assertRaisesRegex(ValueError,"nominal differs"):
            validate_nominals(registry,effective,self.gas)

    def test_missing_evidence_and_false_calibration_are_rejected(self):
        for mutation in ("missing", "calibrated", "duplicate", "bad_grid", "bad_source"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                payload=json.loads(REGISTRY.read_text(encoding="utf-8"))
                if mutation=="missing": payload["parameters"].pop(0)
                if mutation=="calibrated": payload["parameters"][0]["qaif_calibrated"]=True
                if mutation=="duplicate": payload["parameters"].append(payload["parameters"][0])
                if mutation=="bad_grid": payload["parameters"][0]["sweep_values"]=[float("nan")]
                if mutation=="bad_source": payload["parameters"][0]["source_ids"]=["invented"]
                path=Path(temp)/"registry.json"; path.write_text(json.dumps(payload),encoding="utf-8")
                with self.assertRaises(ValueError): load_registry(path,self.template,self.gas)

    def test_profiles_verify_location_and_reject_buried_or_invented_prior(self):
        profiles=validate_profiles(ROOT/"evidence/profiles.json",ROOT/"reference_data")
        self.assertEqual(len(profiles["sites"]),2)
        for kind in ("coordinate", "buried", "prior"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                payload=json.loads(json.dumps(profiles))
                if kind=="coordinate": payload["sites"][0]["latitude"]=25
                if kind=="buried": payload["asset"]["installation"]="buried"
                if kind=="prior": payload["sites"][0]["fault_incidence_prior"]=.1
                path=Path(temp)/"profiles.json"; path.write_text(json.dumps(payload),encoding="utf-8")
                with self.assertRaises(ValueError): validate_profiles(path,ROOT/"reference_data")


class ReplayAndGroupingTests(unittest.TestCase):
    def setUp(self):
        self.config=Config.from_json(ROOT/"examples/fixture_config.json")
        self.step=read_forcing(ROOT/"examples/fixture_forcing.csv")[0]

    def test_hold_refinement_preserves_interval_inputs_not_interpolated_samples(self):
        source=[self.step,replace(self.step,timestamp_s=3600,pressure_pa=2e6),
                replace(self.step,timestamp_s=7200,pressure_pa=3e6)]
        refined=hold_refine(source,600)
        self.assertEqual(len(refined),13)
        self.assertEqual(refined[0],source[0])
        self.assertTrue(all(s.pressure_pa==2e6 for s in refined[1:7]))
        self.assertTrue(all(s.pressure_pa==3e6 for s in refined[7:]))
        for period in (True,0,700):
            with self.assertRaises(ValueError): hold_refine(source,period)

    def test_timeline_physical_start_is_not_one_interval_early(self):
        control=[replace(self.step,timestamp_s=t,event_type="normal_environment") for t in range(0,241,30)]
        spec=_timeline(self.config,"fixture_site","timing_check","mechanical_change",60,120,
                       {"bending_moment_nm":20},30,240)
        event,labels,_,_=build_timeline(self.config,control,spec)
        self.assertEqual([s.timestamp_s for s in event if s.bending_moment_nm], [90,120])
        self.assertTrue(all(a==b for a,b in zip(control,event) if a.timestamp_s<=60))

    def test_stress_guard_checks_unsensed_circumference_and_restraint(self):
        normal=mechanical_stress_guard(self.config,self.step,293.15,200e6)
        self.assertGreater(normal,0)
        hidden=replace(self.config,sensor_theta_rad=1.5707963267948966)
        with self.assertRaisesRegex(ValueError,"elastic stress budget"):
            mechanical_stress_guard(hidden,replace(self.step,bending_moment_nm=1e9),293.15,200e6)
        restrained=replace(self.config,axial_restraint_fraction=1)
        with self.assertRaisesRegex(ValueError,"elastic stress budget"):
            mechanical_stress_guard(restrained,self.step,493.15,200e6)

    def test_grouping_is_transitive_and_rejects_cross_split_branches(self):
        records=[{"record_id":"A","source_tokens":["pressure:P1","weather:W1"]},
                 {"record_id":"B","source_tokens":["pressure:P1","weather:W2"]},
                 {"record_id":"C","source_tokens":["pressure:P2","weather:W2"]},
                 {"record_id":"D","source_tokens":["pressure:P3","weather:W3"]}]
        groups=connected_groups(records)
        self.assertEqual([g["record_ids"] for g in groups],[["A","B","C"],["D"]])
        validate_split_assignment(groups,{"A":"train","B":"train","C":"train","D":"test"})
        with self.assertRaisesRegex(ValueError,"crosses split boundaries"):
            validate_split_assignment(groups,{"A":"train","B":"val","C":"train","D":"test"})
        with self.assertRaisesRegex(ValueError,"cover every record"):
            validate_split_assignment(groups,{"A":"train"})

    def test_run_audit_checks_hashes_units_and_missing_packets(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/"sim"
            simulate_to_directory(ROOT/"examples/fixture_config.json",ROOT/"examples/fixture_forcing.csv",out,42)
            report=audit_run(out,60,200e6)
            self.assertTrue(report["numerically_clean"])
            with (out/"observed.csv").open("a",encoding="utf-8") as handle: handle.write("\n")
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                audit_run(out,60,200e6)

    def test_forced_packet_loss_preserves_noise_stream_after_recovery(self):
        config=replace(self.config,strain_hoop=replace(self.config.strain_hoop,noise_std=1),
                       temperature=replace(self.config.temperature,noise_std=.1),packet_loss_probability=0)
        control,event=Simulator(config,42),Simulator(config,42)
        for t in range(0,301,60):
            inputs=replace(self.step,timestamp_s=t)
            a,la=control.step(inputs)
            b,lb=event.step(replace(inputs,force_missing=60<=t<=120))
            self.assertEqual(la,lb)
            if 60<=t<=120: self.assertFalse(b["packet_valid"])
            else: self.assertEqual(a,b)


if __name__=="__main__": unittest.main()
