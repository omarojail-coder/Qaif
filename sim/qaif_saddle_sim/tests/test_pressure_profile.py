"""Pressure bridge regressions and rejection boundaries; no field calibration."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from qaif_saddle_sim.audit_reference import audit_reference, pressure_variability
from qaif_saddle_sim.io import read_forcing, simulate_to_directory
from qaif_saddle_sim.pressure_profile import load_ntsb_pressure_profile
from qaif_saddle_sim.reference_episode import prepare_reference_episode, _local_pressure

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "reference_data"
CHANNELS = ROOT.parent / "outputs" / "ntsb_pressure_audit_v1"
WEST = CHANNELS / "west_spill_1067220"
PSIG = CHANNELS / "verified_psig_57035"
PDF = SOURCES / "ntsb_cheyenne_scada_7day_pressure.pdf"
TEMPLATE = ROOT / "examples" / "reference_template_config.json"
ASSUMPTIONS = ROOT / "examples" / "reference_gas_assumptions.json"
START = "2025-09-13 15:00"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class PressureProfileTests(unittest.TestCase):
    def _prepare(self, out: Path, **kwargs) -> dict:
        return prepare_reference_episode(
            SOURCES, "red_sea_coast_rain_2024", TEMPLATE, out, ASSUMPTIONS,
            pressure_mode="ntsb_relative_upstream", ntsb_pressure_dir=WEST,
            ntsb_start_local=START, **kwargs,
        )

    def test_real_window_ratios_and_unknown_units_are_auditable(self) -> None:
        hourly, profile = load_ntsb_pressure_profile(WEST, PDF, START, 168)
        self.assertEqual(len(hourly), 168)
        self.assertEqual(profile["selected_record_count"], 4632)
        self.assertEqual(profile["max_internal_sample_gap_minutes"], 12)
        self.assertEqual(profile["window_end_local_exclusive"], "2025-09-20 15:00")
        self.assertFalse(profile["absolute_pressure_conversion_used"])
        self.assertEqual(profile["native_unit"], "unspecified in PDF")
        self.assertEqual(hourly[0]["upstream_pressure_ratio"], 1)
        values = [r["source_native_hourly_median"] for r in hourly]
        self.assertGreater(pressure_variability(values)["lag24_max_abs_native_difference"], 0)

    def test_no_missing_hour_is_silently_filled(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing NTSB pressure hour: 2025-09-14 12:00"):
            load_ntsb_pressure_profile(PSIG, PDF, START, 168)
        hourly, profile = load_ntsb_pressure_profile(PSIG, PDF, START, 12)
        self.assertEqual(len(hourly), 12)
        self.assertEqual(profile["native_unit"], "PSIG")
        self.assertFalse(profile["absolute_pressure_conversion_used"])

    def test_incident_boundary_and_clock_validation(self) -> None:
        hourly, _ = load_ntsb_pressure_profile(WEST, PDF, "2025-09-20 22:00", 1)
        self.assertEqual(hourly[0]["source_local_hour"], "2025-09-20 22:00")
        for start, hours in [("2025-09-20 22:00", 2), ("2025-09-20 23:00", 1)]:
            with self.assertRaisesRegex(ValueError, "held-out incident period"):
                load_ntsb_pressure_profile(WEST, PDF, start, hours)
        for start in ("2025-09-13 15:05", "2025-09-13T15:00Z"):
            with self.assertRaisesRegex(ValueError, "whole hour|source-local"):
                load_ntsb_pressure_profile(WEST, PDF, start, 1)
        for hours in (0, -1, True, 1.5):
            with self.assertRaisesRegex(ValueError, "positive integer"):
                load_ntsb_pressure_profile(WEST, PDF, START, hours)

    def test_source_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            channel = Path(temp) / "channel"
            shutil.copytree(WEST, channel)
            with (channel / "pressure.csv").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "CSV hash mismatch"):
                load_ntsb_pressure_profile(channel, PDF, START, 1)
            fake_pdf = Path(temp) / "changed.pdf"
            fake_pdf.write_bytes(b"changed original")
            with self.assertRaisesRegex(ValueError, "PDF hash mismatch"):
                load_ntsb_pressure_profile(WEST, fake_pdf, START, 1)

    def test_duplicate_minutes_are_collapsed_and_empty_bins_rejected(self) -> None:
        # A modified CSV and manifest are a parser fixture, never a generated
        # scientific source. Check the aggregation rather than assuming the
        # archived source contains duplicates in this particular window.
        with tempfile.TemporaryDirectory() as temp:
            channel = Path(temp) / "fixture"
            shutil.copytree(WEST, channel)
            original = rows(channel / "pressure.csv")
            fields = list(original[0])
            samples = []
            for minute, value in [("15:01", 10), ("15:01", 10), ("15:01", 10),
                                  ("15:01", 100), ("15:02", 20)]:
                row = dict(original[0], source_local_time="2025-09-13 " + minute,
                           source_value=str(value))
                samples.append(row)
            path = channel / "pressure.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(samples)
            manifest_path = channel / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pressure_csv_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            hourly, profile = load_ntsb_pressure_profile(channel, PDF, START, 1)
            self.assertEqual(hourly[0]["source_native_hourly_median"], 15)
            self.assertEqual(profile["duplicate_minute_record_count"], 3)
            with self.assertRaisesRegex(ValueError, "missing NTSB pressure hour"):
                load_ntsb_pressure_profile(channel, PDF, START, 2)

    def test_inconsistent_channel_unit_metadata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            channel = Path(temp) / "fixture"
            shutil.copytree(WEST, channel)
            manifest_path = channel / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unit_source"] = "PSIG"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inconsistent unit metadata"):
                load_ntsb_pressure_profile(channel, PDF, START, 1)

    def test_pressure_mapping_nonperiodicity_and_benchmark_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            old, new = Path(temp) / "periodic", Path(temp) / "nonperiodic"
            periodic = prepare_reference_episode(
                SOURCES, "red_sea_coast_rain_2024", TEMPLATE, old, ASSUMPTIONS,
            )
            manifest = self._prepare(new)
            original, updated = read_forcing(old / "forcing.csv"), read_forcing(new / "forcing.csv")
            before, after = rows(old / "source_diagnostics.csv"), rows(new / "source_diagnostics.csv")
            self.assertEqual(len(updated), 169)
            self.assertNotEqual(periodic["episode_id"], manifest["episode_id"])
            self.assertEqual(periodic["pressure_profile"]["mode"], "periodic_benchmark_surrogate")
            self.assertIsNone(manifest["inferred_constant_upstream_pressure_pa"])
            self.assertEqual(manifest["flow_profile"]["mode"], "periodic_trr154_demand_surrogate")
            self.assertEqual(original[0].pressure_pa, updated[0].pressure_pa)
            gas = manifest["gaslib_properties"]
            initial = manifest["trr_initial_pipe_state"]
            assumptions = manifest["assumptions"]
            for i, (a, b) in enumerate(zip(original, updated)):
                self.assertEqual(a.fluid_temperature_k, b.fluid_temperature_k)
                self.assertEqual(a.ambient_temperature_k, b.ambient_temperature_k)
                self.assertEqual(a.wet_drive, b.wet_drive)
                self.assertEqual(before[i]["surrogate_mass_flow_kg_s"], after[i]["surrogate_mass_flow_kg_s"])
                upstream = float(after[i]["surrogate_upstream_absolute_pressure_pa"])
                self.assertGreaterEqual(upstream, gas["source_pressure_min_pa"])
                self.assertLessEqual(upstream, gas["source_pressure_max_pa"])
                expected = _local_pressure(
                    upstream, float(after[i]["surrogate_mass_flow_kg_s"]),
                    gas["diameter_m"], initial["position_m"],
                    float(after[i]["surrogate_darcy_friction_factor"])
                    * manifest["friction_correction_ratio_to_haaland"],
                    assumptions["compressibility_factor"],
                    8.314462618 / gas["molar_mass_kg_mol"], gas["gas_temperature_k"],
                )
                self.assertAlmostEqual(expected - assumptions["external_pressure_pa"], b.pressure_pa)
                self.assertGreater(b.pressure_pa, 0)
            old_stats = pressure_variability([s.pressure_pa for s in original[1:]])
            new_stats = pressure_variability([s.pressure_pa for s in updated[1:]])
            self.assertEqual(old_stats["lag24_exact_match_fraction"], 1)
            self.assertLess(new_stats["lag24_exact_match_fraction"], 0.1)
            self.assertGreater(new_stats["range_over_own_median_pct"], old_stats["range_over_own_median_pct"])

    def test_reproducible_export_provenance_and_no_metadata_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "first", Path(temp) / "second"
            m1, m2 = self._prepare(first), self._prepare(second)
            self.assertEqual(m1, m2)
            self.assertFalse(m1["training_ready"])
            self.assertIn("ntsb_pressure_profile", m1["source_files"])
            self.assertIn("pressure_hourly_snapshot.csv", m1["output_sha256"])
            sim = Path(temp) / "sim"
            result = simulate_to_directory(first / "config.json", first / "forcing.csv", sim, 42)
            self.assertFalse(result["training_ready"])
            report = audit_reference(first, sim)
            self.assertTrue(report["numerically_clean"])
            self.assertIn("incident_window_excluded", report["checks"])
            forbidden = {"pressure_source_local_hour", "source_native_hourly_median",
                         "upstream_pressure_ratio", "source_pages", "channel_id"}
            for name in ("observed.csv", "context.csv"):
                self.assertFalse(forbidden & set(rows(sim / name)[0]))
            with (first / "pressure_hourly_snapshot.csv").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(ValueError, "prepared file changed"):
                audit_reference(first, sim)

    def test_options_invalid_window_and_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for index, kwargs in enumerate([
                {"pressure_mode": "bad_mode"},
                {"pressure_mode": "ntsb_relative_upstream"},
                {"ntsb_pressure_dir": WEST},
                {"pressure_mode": "ntsb_relative_upstream", "ntsb_pressure_dir": WEST,
                 "ntsb_start_local": "2025-09-20 22:00"},
            ]):
                out = Path(temp) / str(index)
                with self.assertRaises(ValueError):
                    prepare_reference_episode(SOURCES, "red_sea_coast_rain_2024",
                                              TEMPLATE, out, ASSUMPTIONS, **kwargs)
                self.assertFalse(out.exists())
            out = Path(temp) / "full"
            self._prepare(out)
            with self.assertRaises(FileExistsError):
                self._prepare(out)

    def test_out_of_envelope_is_rejected_without_clamping(self) -> None:
        # Artificial invalid ratios exercise a guard only; no invented source
        # profile is exported or used to select operational parameters.
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            hourly, profile = load_ntsb_pressure_profile(WEST, PDF, START, 168)
            hourly[10]["upstream_pressure_ratio"] = 0.8
            out = Path(temp) / "invalid"
            with patch("qaif_saddle_sim.reference_episode.load_ntsb_pressure_profile",
                       return_value=(hourly, profile)):
                with self.assertRaisesRegex(ValueError, "outside declared GasLib source envelope"):
                    self._prepare(out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
