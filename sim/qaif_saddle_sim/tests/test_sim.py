from __future__ import annotations

import csv
import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from qaif_saddle_sim.config import Config
from qaif_saddle_sim.experiment import make_pair
from qaif_saddle_sim.io import read_forcing, simulate_to_directory
from qaif_saddle_sim.model import Simulator, State, advance_physics, pipe_strains
from qaif_saddle_sim.timeline import build_timeline, make_timeline_pair


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "examples" / "fixture_config.json"
FORCING_FILE = ROOT / "examples" / "fixture_forcing.csv"


class PhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = Config.from_json(CONFIG_FILE)
        cls.step = read_forcing(FORCING_FILE)[0]

    def test_pressure_zero_and_linear_response(self) -> None:
        base = replace(self.step, pressure_pa=0)
        zero = pipe_strains(self.config, base, self.config.reference_temperature_k)
        self.assertEqual(zero, (0, 0, 0, 0))
        one = pipe_strains(self.config, replace(base, pressure_pa=1e6), self.config.reference_temperature_k)
        two = pipe_strains(self.config, replace(base, pressure_pa=2e6), self.config.reference_temperature_k)
        for first, second in zip(one, two):
            self.assertAlmostEqual(second, 2 * first)

    def test_bending_has_transverse_poisson_response(self) -> None:
        # Pure uniaxial bending stress must also contract the hoop direction.
        # This constitutive identity is independent of the pipe section formula.
        for angle in (0.0, math.pi / 3, math.pi):
            config = replace(self.config, sensor_theta_rad=angle)
            step = replace(self.step, pressure_pa=0, bending_moment_nm=100,
                           bending_direction_rad=0, event_type="mechanical_change")
            _, _, hoop, axial = pipe_strains(config, step, config.reference_temperature_k)
            self.assertNotEqual(axial, 0)
            self.assertAlmostEqual(hoop, -config.poisson_ratio * axial, places=12)

    def test_thicker_wall_reduces_pressure_hoop_strain(self) -> None:
        thin = pipe_strains(self.config, self.step, self.config.reference_temperature_k)
        thick = pipe_strains(replace(self.config, wall_thickness_m=0.004), self.step,
                              self.config.reference_temperature_k)
        self.assertLess(thick[2], thin[2])

    def test_thermal_equilibrium_and_solar_direction(self) -> None:
        state = State(293.15, 293.15, 0, 293.15, 0)
        advance_physics(self.config, state, self.step, 60)
        self.assertAlmostEqual(state.steel_temperature_k, 293.15, places=8)
        self.assertAlmostEqual(state.coating_temperature_k, 293.15, places=8)
        sun_state = State(293.15, 293.15, 0, 293.15, 0)
        sunny = replace(self.step, solar_w_m2=800, solar_incidence=1)
        advance_physics(self.config, sun_state, sunny, 60)
        self.assertGreater(sun_state.coating_temperature_k, 293.15)

    def test_wetness_requires_open_path_and_stays_bounded(self) -> None:
        closed = State(293.15, 293.15, 0, 293.15, 0)
        rainy = replace(self.step, wet_drive=1, wet_path_open=False)
        advance_physics(self.config, closed, rainy, 60)
        self.assertEqual(closed.wetness, 0)
        opened = State(293.15, 293.15, 0, 293.15, 0)
        advance_physics(self.config, opened, replace(rainy, wet_path_open=True), 1e4)
        self.assertGreater(opened.wetness, 0)
        self.assertLessEqual(opened.wetness, 1)

    def test_coupling_fault_changes_readout_not_latent_state(self) -> None:
        normal = Simulator(self.config, 7).step(self.step)
        faulty = Simulator(self.config, 7).step(
            replace(self.step, hoop_coupling_multiplier=0.2, event_type="sensor_fault")
        )
        self.assertEqual(normal[1]["strain_hoop_microstrain_true"],
                         faulty[1]["strain_hoop_microstrain_true"])
        self.assertNotEqual(normal[0]["strain_hoop_microstrain"],
                            faulty[0]["strain_hoop_microstrain"])

    def test_strict_geometry_and_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            replace(self.config, wall_thickness_m=0.01).validate()
        sim = Simulator(self.config, 1)
        sim.step(self.step)
        with self.assertRaises(ValueError):
            sim.step(self.step)

    def test_strain_channel_lag_filters_pressure_step(self) -> None:
        no_noise = replace(self.config.strain_hoop, noise_std=0, lag_s=100)
        config = replace(self.config, strain_hoop=no_noise)
        sim = Simulator(config, 5)
        first, _ = sim.step(self.step)
        second_step = replace(self.step, timestamp_s=60, pressure_pa=2e6)
        second, _ = sim.step(second_step)
        steady_target = pipe_strains(config, second_step, 293.15)[2] * 1e6 * no_noise.gain
        self.assertGreater(second["strain_hoop_microstrain"], first["strain_hoop_microstrain"])
        self.assertLess(second["strain_hoop_microstrain"], steady_target)

    def test_temperature_gain_is_around_reference_not_absolute_zero(self) -> None:
        channel = replace(self.config.temperature, gain=0.5, noise_std=0)
        config = replace(self.config, temperature=channel)
        observed, _ = Simulator(config, 1).step(self.step)
        self.assertAlmostEqual(observed["temperature_k"], 293.15, places=8)


class ExportTests(unittest.TestCase):
    def test_reproducible_and_no_label_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            manifest = simulate_to_directory(CONFIG_FILE, FORCING_FILE, first, 42)
            simulate_to_directory(CONFIG_FILE, FORCING_FILE, second, 42)
            self.assertFalse(manifest["training_ready"])
            self.assertEqual(manifest["sample_count"], 9)
            for name in ("observed.csv", "latent.csv", "context.csv"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            with (first / "context.csv").open(newline="", encoding="utf-8") as handle:
                context = list(csv.DictReader(handle))
            with (first / "observed.csv").open(newline="", encoding="utf-8") as handle:
                observed = list(csv.DictReader(handle))
            for forbidden in ("event_type", "wet_path_open", "bending_moment_nm",
                              "steel_temperature_k", "hoop_coupling_multiplier",
                              "asset_id", "run_id"):
                self.assertNotIn(forbidden, context[0])
                self.assertNotIn(forbidden, observed[0])
            self.assertEqual(observed[-1]["packet_valid"], "False")
            self.assertEqual(observed[-1]["temperature_k"], "")
            self.assertEqual(observed[-2]["temperature_k"], observed[-3]["temperature_k"])
            self.assertEqual(json.loads((first / "manifest.json").read_text())["seed"], 42)

    def test_refuses_overwrite_and_malformed_forcing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "generated"
            simulate_to_directory(CONFIG_FILE, FORCING_FILE, output, 1)
            with self.assertRaises(FileExistsError):
                simulate_to_directory(CONFIG_FILE, FORCING_FILE, output, 2)
            malformed = Path(temp) / "invalid.csv"
            malformed.write_text("timestamp_s,pressure_pa\n0,1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_forcing(malformed)

    def test_matched_pair_same_context_and_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "pair"
            manifest = make_pair(
                CONFIG_FILE,
                ROOT / "examples" / "baseline_forcing.csv",
                ROOT / "examples" / "wetting_intervention.json",
                output, 12,
            )
            self.assertFalse(manifest["training_ready"])
            self.assertEqual(manifest["event_sample_count"], 4)
            self.assertEqual(manifest["split_group"], "fixture_pipe_001:constructed_smoke_test_001")
            self.assertEqual(
                (output / "control" / "context.csv").read_text(),
                (output / "intervention" / "context.csv").read_text().replace(
                    "fixture_episode_001_intervention", "fixture_episode_001_control"
                ),
            )
            with (output / "control" / "latent.csv").open(newline="", encoding="utf-8") as handle:
                control = list(csv.DictReader(handle))
            with (output / "intervention" / "latent.csv").open(newline="", encoding="utf-8") as handle:
                intervention = list(csv.DictReader(handle))
            self.assertEqual(control[4]["wetness_true"], "0.0")
            self.assertGreater(float(intervention[4]["wetness_true"]), 0)

    def test_pair_rejects_no_effect_and_mismatched_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            no_effect = Path(temp) / "no_effect.json"
            no_effect.write_text(json.dumps({
                "event_type": "interface_wetting", "start_s": 240, "end_s": 480,
                "set": {"wet_path_open": False},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                make_pair(CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                          no_effect, Path(temp) / "no_effect_output", 1)
            mismatch = Path(temp) / "mismatch.json"
            mismatch.write_text(json.dumps({
                "event_type": "sensor_fault", "start_s": 240, "end_s": 480,
                "set": {"bending_moment_nm": 20},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                make_pair(CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                          mismatch, Path(temp) / "mismatch_output", 1)

    def test_case_link_is_provenance_only_and_rejects_unsupported_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            linked = Path(temp) / "linked.json"
            linked.write_text(json.dumps({
                "event_type": "interface_wetting", "start_s": 240, "end_s": 480,
                "set": {"wet_path_open": True},
                "inspired_by_case_id": "QC-02",
            }), encoding="utf-8")
            output = Path(temp) / "linked_pair"
            manifest = make_pair(CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                                 linked, output, 12)
            self.assertEqual(manifest["inspired_by_case_id"], "QC-02")
            self.assertEqual(manifest["case_record_type"], "observed_condition")
            self.assertTrue((output / "inputs" / "case_card_snapshot.json").exists())
            self.assertIsNotNone(manifest["case_card_snapshot_sha256"])
            self.assertFalse(manifest["training_ready"])
            for name in ("observed.csv", "context.csv"):
                self.assertNotIn("QC-02", (output / "intervention" / name).read_text(encoding="utf-8"))

            unsupported = Path(temp) / "unsupported.json"
            unsupported.write_text(json.dumps({
                "event_type": "interface_wetting", "start_s": 240, "end_s": 480,
                "set": {"wet_path_open": True},
                "inspired_by_case_id": "QC-03",
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not support"):
                make_pair(CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                          unsupported, Path(temp) / "unsupported_pair", 12)


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = Config.from_json(CONFIG_FILE)
        cls.baseline = read_forcing(ROOT / "examples" / "baseline_forcing.csv")

    @staticmethod
    def _spec() -> dict:
        return {
            "schema_version": "1",
            "asset_id": "fixture_pipe_001",
            "site_id": "fixture_site_001",
            "base_episode_id": "constructed_smoke_test_001",
            "scenario_family_id": "fixture_mechanical",
            "mechanism_id": "mechanical_change",
            "phases": [{
                "phase_id": "local_load_pulse",
                "event_type": "mechanical_change",
                "start_s": 120,
                "end_s": 360,
                "changes": {"bending_moment_nm": {
                    "mode": "pulse", "base": 0, "peak": 20, "peak_fraction": 0.5,
                }},
            }],
        }

    def test_timeline_case_phases_pre_event_identity_and_separate_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "timeline_pair"
            manifest = make_timeline_pair(
                CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                ROOT / "examples" / "wetting_timeline.json", output, 42,
            )
            self.assertEqual(manifest["phase_sample_counts"], {
                "onset": 1, "continued_ingress": 1, "recovery_observation": 0,
            })
            self.assertEqual(manifest["event_sample_count"], 2)
            self.assertEqual(manifest["inspired_by_case_id"], "QC-02")
            self.assertEqual(manifest["evidence_level"], "test_fixture")
            self.assertFalse(manifest["training_ready"])
            with (output / "inputs" / "intervention_forcing.csv").open(newline="", encoding="utf-8") as handle:
                forcing = list(csv.DictReader(handle))
            self.assertEqual(forcing[4]["wet_path_open"], "1")
            self.assertEqual(forcing[4]["wet_drive"], "0.2")
            self.assertEqual(forcing[5]["wet_path_open"], "1")
            self.assertEqual(forcing[6]["wet_path_open"], "0")
            with (output / "inputs" / "timeline_samples.csv").open(newline="", encoding="utf-8") as handle:
                labels = list(csv.DictReader(handle))
            self.assertEqual([row["phase_id"] for row in labels[4:6]],
                             ["onset", "continued_ingress"])
            self.assertEqual(labels[6]["phase_id"], "recovery_observation")
            self.assertEqual(labels[6]["intervention_applied"], "False")
            branches = {}
            for branch in ("control", "intervention"):
                with (output / branch / "observed.csv").open(newline="", encoding="utf-8") as handle:
                    branches[branch] = list(csv.DictReader(handle))
                for name in ("observed.csv", "context.csv"):
                    self.assertNotIn("QC-02", (output / branch / name).read_text(encoding="utf-8"))
                    self.assertNotIn("phase_id", (output / branch / name).read_text(encoding="utf-8"))
            for index in range(4):
                control = {k: v for k, v in branches["control"][index].items() if k != "run_id"}
                event = {k: v for k, v in branches["intervention"][index].items() if k != "run_id"}
                self.assertEqual(control, event)
            self.assertNotEqual(branches["control"][5]["wetness_index"],
                                branches["intervention"][5]["wetness_index"])
            with (output / "intervention" / "latent.csv").open(newline="", encoding="utf-8") as handle:
                latent = list(csv.DictReader(handle))
            self.assertGreater(float(latent[6]["wetness_true"]), 0)
            self.assertLess(float(latent[7]["wetness_true"]),
                            float(latent[6]["wetness_true"]))
            self.assertEqual(
                manifest["timeline_samples_sha256"],
                hashlib.sha256((output / "inputs" / "timeline_samples.csv").read_bytes()).hexdigest(),
            )
            replay = Path(temp) / "replay"
            make_timeline_pair(CONFIG_FILE, ROOT / "examples" / "baseline_forcing.csv",
                               ROOT / "examples" / "wetting_timeline.json", replay, 42)
            for branch in ("control", "intervention"):
                for name in ("observed.csv", "context.csv", "latent.csv"):
                    self.assertEqual((output / branch / name).read_bytes(),
                                     (replay / branch / name).read_bytes())

    def test_pulse_profile_and_unsampled_peak_validation(self) -> None:
        spec = self._spec()
        steps, labels, counts, _ = build_timeline(self.config, self.baseline, spec)
        self.assertEqual(counts, {"local_load_pulse": 3})
        self.assertEqual([steps[i].bending_moment_nm for i in range(2, 6)], [0, 10, 20, 10])
        self.assertFalse(labels[2]["intervention_applied"])
        self.assertTrue(labels[4]["intervention_applied"])
        spec["phases"][0]["changes"]["bending_moment_nm"]["peak_fraction"] = 1
        with self.assertRaisesRegex(ValueError, "peak_fraction"):
            build_timeline(self.config, self.baseline, spec)

    def test_timeline_rejects_overlap_wrong_case_and_ineffective_phase(self) -> None:
        spec = self._spec()
        spec["phases"].append({
            "phase_id": "overlap", "event_type": "mechanical_change",
            "start_s": 300, "end_s": 420,
            "changes": {"bending_moment_nm": {"mode": "hold", "value": 5}},
        })
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            build_timeline(self.config, self.baseline, spec)
        spec = self._spec()
        spec["inspired_by_case_id"] = "QC-02"
        with self.assertRaisesRegex(ValueError, "does not support"):
            build_timeline(self.config, self.baseline, spec)
        spec = self._spec()
        spec["phases"][0]["changes"]["bending_moment_nm"] = {"mode": "hold", "value": 0}
        with self.assertRaisesRegex(ValueError, "does not change"):
            build_timeline(self.config, self.baseline, spec)
        spec = self._spec()
        spec["mechanism_id"] = "normal_environment"
        spec["phases"].insert(0, {
            "phase_id": "empty_normal", "event_type": "normal_environment",
            "start_s": 0, "end_s": 120, "changes": {},
        })
        with self.assertRaisesRegex(ValueError, "matching mechanism_id"):
            build_timeline(self.config, self.baseline, spec)


if __name__ == "__main__":
    unittest.main()
