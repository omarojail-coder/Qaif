from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qaif_saddle_sim.additional_sources import load_extra_asset,load_native_hourly_archive
from qaif_saddle_sim.coherence_audit import centroid_holdout,shortcut_diagnostic,plan_source_split
from qaif_saddle_sim.config import Config
from qaif_saddle_sim.evidence_registry import sha256
from qaif_saddle_sim.io import read_forcing
from qaif_saddle_sim.io import simulate_to_directory
from qaif_saddle_sim.measurement_validation import compare_measurements
from qaif_saddle_sim.physics_validation import exact_linear_thermal,nonlinear_thermal_reference
from qaif_saddle_sim.model import State,advance_physics
from qaif_saddle_sim.model import Simulator
from qaif_saddle_sim.physics_cache import PhysicsCache
from qaif_saddle_sim.global_source_audit import audit_saved_studies

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"reference_data/additional_v1"


class AdditionalSourceTests(unittest.TestCase):
    def test_reviewed_source_geometry_and_native_unit_limit(self):
        asset=load_extra_asset(ARCHIVE)
        self.assertEqual(asset["inner_diameter_m"],.9)
        self.assertEqual(asset["gas_temperature_k"],283.15)
        self.assertEqual(asset["roughness_m"],1e-6)
        self.assertFalse(asset["training_ready"])
        rows,meta=load_native_hourly_archive(ARCHIVE,"2002-01-01 00:00",72)
        self.assertEqual(len(rows),72)
        self.assertEqual(rows[0]["source_native_hourly_median"],366.50)
        self.assertEqual(rows[0]["upstream_pressure_ratio"],1)
        self.assertFalse(meta["absolute_pressure_conversion_used"])
        self.assertIn("unspecified",meta["native_unit"])

    def test_missing_hour_and_changed_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for name in ("source_manifest.json","san_bruno_pressure.csv","san_bruno_pressure_history.pdf"):
                (target/name).write_bytes((ARCHIVE/name).read_bytes())
            with (target/"san_bruno_pressure.csv").open(encoding="utf-8",newline="") as handle:
                reader=csv.DictReader(handle);columns=reader.fieldnames;rows=list(reader)
            del rows[1]
            with (target/"san_bruno_pressure.csv").open("w",encoding="utf-8",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(ValueError,"hash"):
                load_native_hourly_archive(target,"2002-01-01 00:00",3)
            manifest=json.loads((target/"source_manifest.json").read_text())
            manifest["pressure_csv_sha256"]=sha256(target/"san_bruno_pressure.csv")
            (target/"source_manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"missing"):
                load_native_hourly_archive(target,"2002-01-01 00:00",3)

    def test_cutoff_and_unavailable_window_not_interpolated(self):
        for start,hours in (("2010-09-09 00:00",1),("2002-01-01 00:30",1),("2002-01-08 00:00",1)):
            with self.assertRaises(ValueError):load_native_hourly_archive(ARCHIVE,start,hours)


class IndependentReferenceTests(unittest.TestCase):
    def setUp(self):
        self.config=Config.from_json(ROOT/"examples/fixture_config.json")
        self.step=read_forcing(ROOT/"examples/fixture_forcing.csv")[0]

    def test_linear_thermal_matches_exact_transient_and_equilibrium(self):
        config=replace(self.config,emissivity=0)
        step=replace(self.step,solar_w_m2=0,fluid_temperature_k=320,ambient_temperature_k=290)
        expected=exact_linear_thermal(config,step,(290,290),600)
        state=State(290,290,0,290,0);advance_physics(config,state,step,600)
        self.assertLess(max(abs(a-b) for a,b in zip(expected,(state.steel_temperature_k,state.coating_temperature_k))),.25)
        equilibrium=replace(step,fluid_temperature_k=290)
        self.assertEqual(exact_linear_thermal(config,equilibrium,(290,290),3600),(290,290))

    def test_nonlinear_reference_step_halving(self):
        step=replace(self.step,solar_w_m2=900,sky_temperature_k=270)
        coarse=nonlinear_thermal_reference(self.config,step,(293.15,293.15),60,max_step=.5)
        fine=nonlinear_thermal_reference(self.config,step,(293.15,293.15),60,max_step=.25)
        self.assertLess(max(abs(a-b) for a,b in zip(coarse,fine)),1e-4)

    def test_shared_cache_preserves_sensor_noise_and_wetting_sequences(self):
        cache=PhysicsCache(max_entries=20)
        steps=read_forcing(ROOT/"examples/fixture_forcing.csv")
        configurations=[self.config,replace(self.config,strain_hoop=replace(self.config.strain_hoop,gain=.4,noise_std=2))]
        for config in configurations:
            for mechanism in ("baseline","wet","gap","bending"):
                plain=Simulator(config,17);cached=Simulator(config,17,physics_cache=cache)
                for step in steps:
                    if step.timestamp_s>=120:
                        if mechanism=="wet":step=replace(step,wet_path_open=True,wet_drive=.7)
                        elif mechanism=="gap":step=replace(step,force_missing=True)
                        elif mechanism=="bending":step=replace(step,bending_moment_nm=100)
                    self.assertEqual(plain.step(step),cached.step(step))
        self.assertGreater(cache.hits,0)
        self.assertLessEqual(len(cache.values),20)


class ShortcutAndSplitTests(unittest.TestCase):
    def examples(self,leak=False):
        return [{"group":f"g{g}","pair":f"g{g}p{p}","label":label,
                 "x":[float(g),float(p),100*label if leak else 0]}
                for g in range(3) for p in range(4) for label in (0,1)]

    def test_pair_null_and_planted_shortcut(self):
        clean=shortcut_diagnostic(self.examples(),permutations=19)
        self.assertEqual(clean["balanced_accuracy"],.5)
        self.assertEqual(clean["one_sided_permutation_p"],1)
        contaminated=shortcut_diagnostic(self.examples(True),permutations=19)
        self.assertEqual(contaminated["balanced_accuracy"],1)
        self.assertLessEqual(contaminated["one_sided_permutation_p"],.05)

    def test_source_split_rejects_transitive_reuse(self):
        connected=[{"record_id":"a","source_tokens":["A","P"]},
                   {"record_id":"b","source_tokens":["P","W"]},
                   {"record_id":"c","source_tokens":["W","B"]}]
        self.assertEqual(plan_source_split(connected)["status"],"unavailable")
        independent=[{"record_id":str(i),"source_tokens":[str(i)]} for i in range(3)]
        plan=plan_source_split(independent)
        self.assertEqual(plan["status"],"proposed_only")
        self.assertFalse(plan["train_validation_test_created"])
        self.assertEqual(set(plan["assignments"].values()),{"train","validation","test"})

    def test_one_component_classifier_unavailable(self):
        examples=[{**row,"group":"one"} for row in self.examples()]
        self.assertEqual(centroid_holdout(examples)["status"],"unavailable")

    def test_old_study_can_join_previously_separate_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/name for name in ("new","old")]
            studies=[{"pairs":[{"record_id":"a","source_tokens":["assetA","weatherX"]},
                                {"record_id":"b","source_tokens":["assetB","weatherY"]}]},
                     {"pairs":[{"record_id":"a","source_tokens":["weatherX","weatherY"]}]}]
            for path,data in zip(paths,studies):
                path.mkdir();(path/"summary.json").write_text(json.dumps(data),encoding="utf-8")
            self.assertEqual(audit_saved_studies(paths[:1])["source_component_count"],2)
            self.assertEqual(audit_saved_studies(paths)["source_component_count"],1)


class MeasurementContractTests(unittest.TestCase):
    def fixture(self,target):
        sim=target/"sim"
        simulate_to_directory(ROOT/"examples/fixture_config.json",ROOT/"examples/fixture_forcing.csv",sim,42)
        with (sim/"observed.csv").open(encoding="utf-8",newline="") as handle:
            rows=list(csv.DictReader(handle))
        measurement=target/"fixture_measurement.csv"
        with measurement.open("w",encoding="utf-8",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=["timestamp_s","temperature_k"]);writer.writeheader()
            writer.writerows({"timestamp_s":row["timestamp_s"],"temperature_k":float(row["temperature_k"])-.5}
                             for row in rows if row["packet_valid"]=="True")
        metadata={"schema_version":"1","declared_independent_measurements":True,"source_kind":"bench_measurement",
                  "source_uri":"unit-test-fixture-only","measurement_protocol_uri":"unit-test-fixture-only",
                  "measurement_csv_sha256":sha256(measurement),"model_config_snapshot_sha256":sha256(sim/"config_snapshot.json"),
                  "installation":"aboveground","time_alignment":"same elapsed time; no interpolation",
                  "channel_units":{"temperature_k":"K"},"comparison_tolerances":{"temperature_k":{"rmse_max":1,"abs_bias_max":1}}}
        meta=target/"fixture_metadata.json";meta.write_text(json.dumps(metadata),encoding="utf-8")
        return sim,measurement,meta,metadata

    def test_declared_error_and_no_auto_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim,trace,meta,metadata=self.fixture(Path(tmp))
            result=compare_measurements(sim,trace,meta)
            self.assertAlmostEqual(result["channels"]["temperature_k"]["rmse"],.5)
            self.assertTrue(result["comparison_within_declared_limits"])
            self.assertFalse(result["qaif_calibrated"]);self.assertFalse(result["training_ready"])
            metadata["comparison_tolerances"]["temperature_k"]["rmse_max"]=.1
            meta.write_text(json.dumps(metadata),encoding="utf-8")
            self.assertFalse(compare_measurements(sim,trace,meta)["comparison_within_declared_limits"])

    def test_units_source_and_integrity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim,trace,meta,metadata=self.fixture(Path(tmp))
            for key,value in (("channel_units",{"temperature_k":"C"}),("declared_independent_measurements",False),
                              ("measurement_csv_sha256","bad")):
                invalid={**metadata,key:value};meta.write_text(json.dumps(invalid),encoding="utf-8")
                with self.assertRaises(ValueError):compare_measurements(sim,trace,meta)
            meta.write_text(json.dumps(metadata),encoding="utf-8")
            with (sim/"observed.csv").open("a",encoding="utf-8") as handle:handle.write("modified\n")
            with self.assertRaisesRegex(ValueError,"simulation.*hash"):
                compare_measurements(sim,trace,meta)


if __name__=="__main__":unittest.main()
