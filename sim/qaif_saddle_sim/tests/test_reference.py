"""Checks on the archived source-to-forcing bridge, not field validation."""

from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from qaif_saddle_sim.io import read_forcing, simulate_to_directory
from qaif_saddle_sim.audit_reference import audit_reference
from qaif_saddle_sim.reference_episode import prepare_reference_episode

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "reference_data"
TEMPLATE = ROOT / "examples" / "reference_template_config.json"
ASSUMPTIONS = ROOT / "examples" / "reference_gas_assumptions.json"
ASSUMPTIONS_100M = ROOT / "examples" / "reference_gas_assumptions_100m.json"
ASSUMPTIONS_1000M = ROOT / "examples" / "reference_gas_assumptions_1000m.json"


class ReferenceBridgeTests(unittest.TestCase):
    def _prepare(self, episode: str, out: Path) -> dict:
        return prepare_reference_episode(SOURCES, episode, TEMPLATE, out, ASSUMPTIONS)

    def test_weather_units_pressure_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "episode"
            manifest = self._prepare("red_sea_coast_rain_2024", out)
            steps = read_forcing(out / "forcing.csv")
            with (out / "source_diagnostics.csv").open(newline="", encoding="utf-8") as handle:
                diagnostics = list(csv.DictReader(handle))
            self.assertEqual(len(steps), 169)
            self.assertEqual(manifest["weather_interval_count"], 168)
            self.assertFalse(manifest["training_ready"])
            self.assertEqual(steps[1].timestamp_s - steps[0].timestamp_s, 3600)
            self.assertAlmostEqual(steps[0].ambient_temperature_k,
                                   float(diagnostics[0]["nasa_air_c"]) + 273.15)
            self.assertAlmostEqual(steps[0].solar_w_m2,
                                   float(diagnostics[0]["nasa_solar_wh_m2"]))
            self.assertAlmostEqual(steps[0].sky_temperature_k**4
                                   * 5.670374419e-8,
                                   float(diagnostics[0]["nasa_longwave_wh_m2"]), places=7)
            self.assertAlmostEqual(float(diagnostics[0]["surrogate_absolute_pressure_pa"])
                                   - steps[0].pressure_pa, 101325.0, places=5)
            self.assertAlmostEqual(float(diagnostics[0]["surrogate_absolute_pressure_pa"]),
                                   manifest["trr_initial_pipe_state"]["pressure_pa"], places=4)
            self.assertTrue(any(step.wet_drive > 0 for step in steps))
            self.assertTrue(all(not step.wet_path_open for step in steps))
            pressures = [float(x["surrogate_absolute_pressure_pa"]) for x in diagnostics]
            flows = [float(x["surrogate_mass_flow_kg_s"]) for x in diagnostics]
            self.assertLess(pressures[flows.index(max(flows))],
                            pressures[flows.index(min(flows))])
            self.assertEqual(set(manifest["source_files"]),
                             {"red_sea_coast_rain_2024", "trr_boundary", "trr_initial",
                              "gaslib_network"})
            self.assertEqual(manifest["gaslib_properties"]["pipe_from_node"], "node_52")
            self.assertEqual(manifest["gaslib_properties"]["pipe_to_node"], "node_53")
            self.assertEqual(manifest["gaslib_properties"]["gas_properties_identical_across_source_count"], 3)

    def test_weather_driven_simulation_runs_with_separated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "episode"
            self._prepare("inland_desert_summer_2024", out)
            sim = Path(temp) / "sim"
            result = simulate_to_directory(out / "config.json", out / "forcing.csv", sim, 12)
            self.assertEqual(result["sample_count"], 169)
            self.assertFalse(result["training_ready"])
            self.assertIsNotNone(result["reference_manifest_sha256"])
            self.assertTrue((sim / "reference_manifest_snapshot.json").is_file())
            with (sim / "observed.csv").open(newline="", encoding="utf-8") as handle:
                observed = list(csv.DictReader(handle))
            self.assertNotIn("event_type", observed[0])
            self.assertNotIn("asset_id", observed[0])
            self.assertTrue(all(math.isfinite(float(row["temperature_k"]))
                                for row in observed if row["temperature_k"]))
            report = audit_reference(out, sim)
            self.assertTrue(report["numerically_clean"])
            self.assertFalse(report["training_ready"])

    def test_changed_archived_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            mirror = Path(temp) / "sources"
            mirror.mkdir()
            manifest = json.loads((SOURCES / "source_manifest.json").read_text())
            (mirror / "source_manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "missing or changed source"):
                prepare_reference_episode(mirror, "red_sea_coast_summer_2024",
                                          TEMPLATE, Path(temp) / "out", ASSUMPTIONS)

    def test_annual_archive_can_yield_a_nonoverlapping_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "week"
            manifest = prepare_reference_episode(
                SOURCES, "inland_desert_year_2024", TEMPLATE, out, ASSUMPTIONS,
                window_start_utc="2024041300", window_hours=168,
            )
            self.assertEqual(manifest["weather_interval_count"], 168)
            self.assertEqual(manifest["sample_count"], 169)
            self.assertEqual(manifest["weather_first_utc_hour"], "2024041300")
            self.assertEqual(manifest["quality_summary"]["rain_hours"], 57)
            with self.assertRaisesRegex(ValueError, "unavailable"):
                prepare_reference_episode(
                    SOURCES, "inland_desert_year_2024", TEMPLATE,
                    Path(temp) / "missing", ASSUMPTIONS,
                    window_start_utc="2024123100", window_hours=168,
                )

    def test_axial_exchange_is_explicit_bounded_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            outputs = []
            for path in (ASSUMPTIONS, ASSUMPTIONS_100M, ASSUMPTIONS_1000M):
                out = Path(temp) / path.stem
                manifest = prepare_reference_episode(
                    SOURCES, "inland_desert_summer_2024", TEMPLATE, out, path,
                )
                self.assertFalse(manifest["training_ready"])
                with (out / "source_diagnostics.csv").open(newline="", encoding="utf-8") as handle:
                    diagnostics = list(csv.DictReader(handle))
                outputs.append((manifest, read_forcing(out / "forcing.csv"), diagnostics))
            inlet = outputs[0][0]["gaslib_properties"]["gas_temperature_k"]
            for index in (1, 30, 90, 168):
                fixed, short, long = (item[1][index].fluid_temperature_k for item in outputs)
                self.assertAlmostEqual(fixed, inlet)
                # More exposed length approaches the same effective environment.
                environment = float(outputs[2][2][index]["axial_effective_environment_k"])
                self.assertLessEqual(abs(long - environment), abs(short - environment))
                self.assertGreater(abs(long - inlet), abs(short - inlet))
            self.assertEqual(outputs[1][0]["assumptions"]["effective_axial_exposure_length_m"], 100)

    def test_axial_length_cannot_exceed_saddle_distance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            assumptions = json.loads(ASSUMPTIONS.read_text(encoding="utf-8"))
            assumptions["effective_axial_exposure_length_m"] = 99999
            path = Path(temp) / "invalid.json"
            path.write_text(json.dumps(assumptions), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot exceed saddle distance from pipe start"):
                prepare_reference_episode(SOURCES, "inland_desert_summer_2024",
                                          TEMPLATE, Path(temp) / "out", path)


if __name__ == "__main__":
    unittest.main()
