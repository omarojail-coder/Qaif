"""Turn public weather and gas benchmarks into auditable local forcing.

The gas calculation is a quasi-steady single-pipe surrogate. It does not
solve the TRR154 network or reproduce pressure at a Saudi saddle.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, fields
from pathlib import Path

from .config import Config
from .model import STEFAN_BOLTZMANN, Step
from .pressure_profile import PRESSURE_MODES, load_ntsb_pressure_profile

TRR_NS = {"t": "https://www.trr154.fau.de/transient-data"}
GAS_NS = {"g": "http://gaslib.zib.de/Gas"}
R_UNIVERSAL = 8.314462618  # J/(mol K)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_file(directory: Path, entry: dict) -> Path:
    path = directory / entry["path"]
    if not path.is_file() or _sha256(path) != entry["sha256"]:
        raise ValueError(f"missing or changed source file: {path}")
    return path


def _value(parent: ET.Element, tag: str, ns: dict[str, str], unit: str | None = None) -> float:
    element = parent.find(tag, ns)
    if element is None or (unit is not None and element.get("unit") != unit):
        raise ValueError(f"missing {tag} or unexpected unit")
    return float(element.attrib["value"])


def _weather_rows(path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "T2M": "C", "WS10M": "m/s", "ALLSKY_SFC_SW_DWN": "Wh/m^2",
        "ALLSKY_SFC_LW_DWN": "Wh/m^2", "PRECTOTCORR": "mm/hour",
    }
    for name, unit in expected.items():
        if payload["parameters"][name]["units"] != unit:
            raise ValueError(f"unexpected POWER units for {name}")
    source = payload["properties"]["parameter"]
    times = list(source["T2M"])
    if not times or any(set(source[name]) != set(times) for name in expected):
        raise ValueError("POWER parameters have mismatched or empty timestamps")
    rows = []
    previous_hour = None
    for key in times:
        hour = dt.datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
        if previous_hour is not None and hour - previous_hour != dt.timedelta(hours=1):
            raise ValueError("POWER timestamps are not consecutive UTC hours")
        previous_hour = hour
        values = {name: float(source[name][key]) for name in expected}
        if (any(not math.isfinite(v) or v == payload["header"]["fill_value"]
                for v in values.values()) or values["WS10M"] < 0
                or values["ALLSKY_SFC_SW_DWN"] < 0
                or values["ALLSKY_SFC_LW_DWN"] <= 0
                or values["PRECTOTCORR"] < 0):
            raise ValueError(f"missing or invalid POWER value at {key}")
        rows.append({"utc_hour": key, **values})
    return rows, payload["parameters"]


def _gaslib_pipe_and_gas(path: Path) -> dict:
    root = ET.parse(path).getroot()
    pipe = root.find('.//g:pipe[@id="p_br52"]', GAS_NS)
    source = root.find('.//g:source[@id="node_1"]', GAS_NS)
    if pipe is None or source is None:
        raise ValueError("GasLib-134 expected pipe p_br52 and source node_1")
    reference_temperature = _value(source, "g:gasTemperature", GAS_NS, "K")
    reference_molar_mass = _value(source, "g:molarMass", GAS_NS, "kg_per_kmol")
    all_sources = root.findall('.//g:source', GAS_NS)
    if not all_sources or any(
        abs(_value(candidate, "g:gasTemperature", GAS_NS, "K") - reference_temperature) > 1e-9
        or abs(_value(candidate, "g:molarMass", GAS_NS, "kg_per_kmol") - reference_molar_mass) > 1e-9
        for candidate in all_sources
    ):
        raise ValueError("GasLib source gases differ; a single source gas is not defensible")
    return {
        "pipe_id": "p_br52",
        "diameter_m": _value(pipe, "g:diameter", GAS_NS, "mm") / 1000,
        "pipe_length_m": _value(pipe, "g:length", GAS_NS, "km") * 1000,
        "roughness_m": _value(pipe, "g:roughness", GAS_NS, "m"),
        "benchmark_heat_transfer_coefficient_w_m2k": _value(
            pipe, "g:heatTransferCoefficient", GAS_NS, "W_per_m_square_per_K"),
        "pipe_from_node": pipe.attrib["from"],
        "pipe_to_node": pipe.attrib["to"],
        "source_id": "node_1",
        "gas_properties_identical_across_source_count": len(all_sources),
        "gas_temperature_k": reference_temperature,
        "molar_mass_kg_mol": reference_molar_mass / 1000,
        "source_pressure_min_pa": _value(source, "g:pressureMin", GAS_NS, "bar") * 1e5,
        "source_pressure_max_pa": _value(source, "g:pressureMax", GAS_NS, "bar") * 1e5,
    }


def _initial_pipe_state(path: Path, length_m: float) -> dict:
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    edge = root.find('.//t:edge[@id="p_br52"]', TRR_NS)
    if edge is None:
        raise ValueError("TRR154 initial state lacks p_br52")
    points = []
    for item in edge.findall("t:edgedata", TRR_NS):
        points.append((
            _value(item, "t:space", TRR_NS, "m"),
            _value(item, "t:massflow", TRR_NS, "kg_per_s"),
            _value(item, "t:pressure", TRR_NS, "bar") * 1e5,
        ))
    if not points or abs(points[-1][0] - length_m) > 1:
        raise ValueError("TRR154 initial pipe length differs from GasLib network")
    position, mass_flow, pressure = min(points, key=lambda p: abs(p[0] - length_m / 2))
    if mass_flow <= 0 or pressure <= 0 or points[0][0] != 0 or points[0][2] <= pressure:
        raise ValueError("TRR154 initial pipe state is not positive forward flow")
    return {"position_m": position, "mass_flow_kg_s": mass_flow,
            "pressure_pa": pressure, "pipe_start_pressure_pa": points[0][2]}


def _demand_shape(path: Path) -> dict[int, float]:
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    total: dict[int, float] = {}
    for node in root.findall("./t:nodes/t:node", TRR_NS):
        for item in node.findall("t:nodedata", TRR_NS):
            massflow = item.find("t:massflow", TRR_NS)
            if massflow is None:
                continue
            value = float(massflow.attrib["value"])
            if value >= 0:
                continue
            t = int(_value(item, "t:time", TRR_NS, "s"))
            total[t] = total.get(t, 0.0) - value
    if 0 not in total or total[0] <= 0 or 86400 not in total:
        raise ValueError("TRR154 demand shape must span 0 to 86400 seconds")
    return {t: value / total[0] for t, value in total.items()}


def _friction_factor(reynolds: float, relative_roughness: float) -> float:
    if not 3000 <= reynolds <= 1e8:
        raise ValueError("Haaland turbulent friction model outside Reynolds range")
    term = (relative_roughness / 3.7) ** 1.11 + 6.9 / reynolds
    return (-1.8 * math.log10(term)) ** -2


def _internal_h(mass_flow: float, diameter: float, roughness: float,
                cp: float, mu: float, conductivity: float) -> tuple[float, float, float]:
    reynolds = 4 * mass_flow / (math.pi * diameter * mu)
    prandtl = cp * mu / conductivity
    if not 3000 <= reynolds <= 5e6 or not 0.5 <= prandtl <= 2000:
        raise ValueError("Gnielinski internal heat transfer model outside range")
    friction = _friction_factor(reynolds, roughness / diameter)
    nu = ((friction / 8) * (reynolds - 1000) * prandtl
          / (1 + 12.7 * math.sqrt(friction / 8) * (prandtl ** (2 / 3) - 1)))
    return nu * conductivity / diameter, reynolds, friction


def _external_h(wind_10m: float, outer_diameter: float,
                wind_height_factor: float) -> float:
    # Churchill-Bernstein circular-cylinder crossflow using declared nominal
    # air properties; a conservative floor represents unresolved free convection.
    air_density = 1.2
    air_mu = 1.8e-5
    air_k = 0.026
    air_pr = 0.71
    velocity = wind_10m * wind_height_factor
    reynolds = air_density * velocity * outer_diameter / air_mu
    if reynolds == 0:
        return 5.0
    nu = (0.3 + (0.62 * math.sqrt(reynolds) * air_pr ** (1 / 3)
                  / (1 + (0.4 / air_pr) ** (2 / 3)) ** 0.25)
          * (1 + (reynolds / 282000) ** (5 / 8)) ** (4 / 5))
    return max(5.0, nu * air_k / outer_diameter)


def _local_pressure(p_upstream_pa: float, mass_flow: float, diameter: float,
                    length: float, friction: float, z: float,
                    gas_constant_specific: float, gas_temperature_k: float) -> float:
    area = math.pi * diameter * diameter / 4
    drop_of_squared_pressure = (friction * length / diameter * mass_flow**2
                                * z * gas_constant_specific * gas_temperature_k / area**2)
    radicand = p_upstream_pa**2 - drop_of_squared_pressure
    if radicand <= 0:
        raise ValueError("surrogate segment pressure squared is nonpositive")
    return math.sqrt(radicand)


def _axial_gas_temperature(inlet_k: float, *, mass_flow_kg_s: float,
                           cp_j_kgk: float, h_inner_w_m2k: float,
                           h_outer_w_m2k: float, ambient_k: float, sky_k: float,
                           solar_w_m2: float, solar_incidence: float,
                           effective_length_m: float, config: Config) -> tuple[float, float, float]:
    """Quasi-steady Sukhov-type axial exchange using one weather cell.

    The effective length is a scenario parameter, not an inferred actual
    aboveground route length. The exterior is linearized at ambient K.
    """
    if effective_length_m == 0:
        return inlet_k, ambient_k, 0.0
    r_i = config.inner_radius_m
    r_s = config.steel_outer_radius_m
    r_c = config.coating_outer_radius_m
    h_radiative = (config.emissivity * STEFAN_BOLTZMANN
                   * (ambient_k + sky_k) * (ambient_k**2 + sky_k**2))
    h_external = h_outer_w_m2k + h_radiative
    solar_absorbed = config.solar_absorptivity * solar_incidence * solar_w_m2
    effective_environment_k = (
        h_outer_w_m2k * ambient_k + h_radiative * sky_k + solar_absorbed
    ) / h_external
    resistance_k_m_w = (
        1 / (h_inner_w_m2k * 2 * math.pi * r_i)
        + math.log(r_s / r_i) / (2 * math.pi * config.steel.conductivity_w_mk)
        + math.log(r_c / r_s) / (2 * math.pi * config.coating.conductivity_w_mk)
        + 1 / (h_external * 2 * math.pi * r_c)
    )
    exponent = effective_length_m / (resistance_k_m_w * mass_flow_kg_s * cp_j_kgk)
    local_k = effective_environment_k + (inlet_k - effective_environment_k) * math.exp(-exponent)
    return local_k, effective_environment_k, exponent


def prepare_reference_episode(source_dir: str | Path, episode: str,
                              template_path: str | Path, output_dir: str | Path,
                              gas_assumptions_path: str | Path,
                              *, window_start_utc: str | None = None,
                              window_hours: int | None = None,
                              pressure_mode: str = "periodic_benchmark_surrogate",
                              ntsb_pressure_dir: str | Path | None = None,
                              ntsb_start_local: str | None = None) -> dict:
    """Build baseline forcing and config; external, derived, assumed fields stay separate."""
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    if episode not in manifest["entries"] or not episode.endswith("2024"):
        raise ValueError(f"unknown reference episode: {episode}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    if pressure_mode not in PRESSURE_MODES:
        raise ValueError(f"unknown pressure mode: {pressure_mode}")
    if pressure_mode == "ntsb_relative_upstream":
        if ntsb_pressure_dir is None or ntsb_start_local is None:
            raise ValueError("NTSB pressure mode requires ntsb_pressure_dir and ntsb_start_local")
    elif ntsb_pressure_dir is not None or ntsb_start_local is not None:
        raise ValueError("NTSB options require ntsb_relative_upstream pressure mode")
    entries = manifest["entries"]
    paths = {key: _checked_file(source_dir, entries[key]) for key in
             (episode, "trr_boundary", "trr_initial", "gaslib_network")}
    weather, power_units = _weather_rows(paths[episode])
    if (window_start_utc is None) != (window_hours is None):
        raise ValueError("window_start_utc and window_hours must be supplied together")
    if window_start_utc is not None:
        if not isinstance(window_hours, int) or isinstance(window_hours, bool) or window_hours < 1:
            raise ValueError("window_hours must be a positive integer")
        matches = [index for index, row in enumerate(weather)
                   if row["utc_hour"] == window_start_utc]
        if len(matches) != 1 or len(weather[matches[0]:matches[0] + window_hours]) != window_hours:
            raise ValueError("requested UTC weather window is unavailable")
        weather = weather[matches[0]:matches[0] + window_hours]
        prepared_id = f"{episode}_{window_start_utc}_{window_hours}h"
    else:
        prepared_id = episode
    pressure_hours, pressure_profile = [], {"mode": pressure_mode}
    if pressure_mode == "ntsb_relative_upstream":
        pressure_hours, pressure_profile = load_ntsb_pressure_profile(
            ntsb_pressure_dir, source_dir / "ntsb_cheyenne_scada_7day_pressure.pdf",
            ntsb_start_local, len(weather),
        )
        start_id = pressure_hours[0]["source_local_hour"].replace("-", "").replace(":", "").replace(" ", "T")
        prepared_id += (f"_ntsb{pressure_profile['channel_id']}_{start_id}"
                        f"_{pressure_profile['pressure_csv_sha256'][:12]}")
    gas = _gaslib_pipe_and_gas(paths["gaslib_network"])
    initial = _initial_pipe_state(paths["trr_initial"], gas["pipe_length_m"])
    demand = _demand_shape(paths["trr_boundary"])
    assumptions = json.loads(Path(gas_assumptions_path).read_text(encoding="utf-8"))
    for key in ("compressibility_factor", "heat_capacity_j_kgk", "viscosity_pa_s",
                "thermal_conductivity_w_mk", "wind_height_factor",
                "solar_incidence_factor", "wet_drive_mm_h_at_one",
                "external_pressure_pa"):
        value = assumptions[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive finite")
    axial_length = assumptions["effective_axial_exposure_length_m"]
    if (not isinstance(axial_length, (int, float)) or isinstance(axial_length, bool)
            or not math.isfinite(axial_length) or axial_length < 0):
        raise ValueError("effective_axial_exposure_length_m must be nonnegative finite")
    if assumptions["compressibility_factor"] > 1.2 or assumptions["wind_height_factor"] > 1 or assumptions["solar_incidence_factor"] > 1:
        raise ValueError("assumption factor outside declared bounds")
    template = json.loads(Path(template_path).read_text(encoding="utf-8"))
    template.update({
        "asset_id": "gaslib134_p_br52_surrogate",
        "run_id": prepared_id,
        "source_episode_id": prepared_id,
        "parameter_basis": "research_sweep",
        "inner_diameter_m": gas["diameter_m"],
        "reference_temperature_k": gas["gas_temperature_k"],
        "initial_steel_temperature_k": gas["gas_temperature_k"],
        "initial_coating_temperature_k": gas["gas_temperature_k"],
        "initial_sensor_temperature_k": gas["gas_temperature_k"],
    })
    # Validate through the existing config contract before writing outputs.
    config_text = json.dumps(template, indent=2) + "\n"
    # Validate all inputs and derived steps before creating any output files.
    with tempfile.TemporaryDirectory() as temp:
        validation_path = Path(temp) / "config.json"
        validation_path.write_text(config_text, encoding="utf-8")
        config = Config.from_json(validation_path)
    diameter, roughness = gas["diameter_m"], gas["roughness_m"]
    length = initial["position_m"]
    if axial_length > length:
        raise ValueError("effective axial exposure cannot exceed saddle distance from pipe start")
    r_specific = R_UNIVERSAL / gas["molar_mass_kg_mol"]
    cp, mu, conductivity = (assumptions["heat_capacity_j_kgk"],
                             assumptions["viscosity_pa_s"],
                             assumptions["thermal_conductivity_w_mk"])
    z = assumptions["compressibility_factor"]
    h_ref, re_ref, f_ref = _internal_h(initial["mass_flow_kg_s"], diameter,
                                      roughness, cp, mu, conductivity)
    area = math.pi * diameter**2 / 4
    p_upstream = initial["pipe_start_pressure_pa"]
    effective_friction = (
        (p_upstream**2 - initial["pressure_pa"]**2) * diameter * area**2
        / (length * initial["mass_flow_kg_s"]**2 * z * r_specific
           * gas["gas_temperature_k"])
    )
    if not 0.005 <= effective_friction <= 0.1:
        raise ValueError("initial-state-calibrated friction outside plausible turbulent range")
    forcing: list[dict] = []
    diagnostics: list[dict] = []
    # At t=0 the simulator initializes state without integrating physics. A
    # separate end-of-hour sample is needed for every archived weather hour.
    for index in range(len(weather) + 1):
        row = weather[0] if index == 0 else weather[index - 1]
        t = index * 3600
        day_second = (max(0, index - 1) * 3600) % 86400
        if day_second not in demand:
            raise ValueError(f"TRR154 missing hour {day_second}")
        mass_flow = initial["mass_flow_kg_s"] * demand[day_second]
        h_inner, reynolds, friction = _internal_h(mass_flow, diameter, roughness,
                                                 cp, mu, conductivity)
        source_hour = pressure_hours[max(0, index - 1)] if pressure_hours else None
        pressure_ratio = source_hour["upstream_pressure_ratio"] if source_hour else 1.0
        current_upstream = p_upstream * pressure_ratio
        if source_hour is not None and not (
            gas["source_pressure_min_pa"] <= current_upstream <= gas["source_pressure_max_pa"]
        ):
            # These source-node limits are a declared benchmark guard, not
            # verified node_52/node_53 operating limits or a clamp.
            raise ValueError("mapped inlet pressure outside declared GasLib source envelope")
        pressure = _local_pressure(current_upstream, mass_flow, diameter, length,
                                   effective_friction * friction / f_ref,
                                   z, r_specific, gas["gas_temperature_k"])
        if source_hour is not None and pressure <= assumptions["external_pressure_pa"]:
            raise ValueError("mapped absolute pressure must exceed external pressure")
        ambient = row["T2M"] + 273.15
        # Hourly Wh/m² divided by exactly one hour is the hourly mean W/m².
        solar = row["ALLSKY_SFC_SW_DWN"]
        longwave = row["ALLSKY_SFC_LW_DWN"]
        sky = (longwave / STEFAN_BOLTZMANN) ** 0.25
        h_outer = _external_h(row["WS10M"], 2 * config.coating_outer_radius_m,
                              assumptions["wind_height_factor"])
        fluid_temperature, effective_environment, axial_exponent = _axial_gas_temperature(
            gas["gas_temperature_k"], mass_flow_kg_s=mass_flow, cp_j_kgk=cp,
            h_inner_w_m2k=h_inner, h_outer_w_m2k=h_outer, ambient_k=ambient,
            sky_k=sky, solar_w_m2=solar,
            solar_incidence=assumptions["solar_incidence_factor"],
            effective_length_m=axial_length, config=config,
        )
        wet_drive = min(1.0, row["PRECTOTCORR"] / assumptions["wet_drive_mm_h_at_one"])
        step = Step(
            timestamp_s=t, pressure_pa=max(0.0, pressure - assumptions["external_pressure_pa"]),
            fluid_temperature_k=fluid_temperature,
            ambient_temperature_k=ambient, sky_temperature_k=sky,
            solar_w_m2=solar,
            solar_incidence=assumptions["solar_incidence_factor"],
            h_inner_w_m2k=h_inner, h_outer_w_m2k=h_outer,
            wet_drive=wet_drive, wet_path_open=False,
            drying_rate_multiplier=1.0, bending_moment_nm=0.0,
            bending_direction_rad=0.0, hoop_coupling_multiplier=1.0,
            axial_coupling_multiplier=1.0, temperature_flatline=False,
            wetness_flatline=False, force_missing=False,
            event_type="normal_environment",
        )
        step.validate()
        values = asdict(step)
        for key in ("wet_path_open", "temperature_flatline", "wetness_flatline", "force_missing"):
            values[key] = int(values[key])
        forcing.append(values)
        diagnostics.append({
            "timestamp_s": t,
            "utc_hour": "initialization" if index == 0 else row["utc_hour"],
            "nasa_air_c": row["T2M"], "nasa_wind_10m_m_s": row["WS10M"],
            "nasa_solar_wh_m2": solar, "nasa_longwave_wh_m2": longwave,
            "nasa_rain_mm_h": row["PRECTOTCORR"],
            "trr_total_sink_demand_ratio": demand[day_second],
            "surrogate_mass_flow_kg_s": mass_flow,
            "surrogate_absolute_pressure_pa": pressure,
            "surrogate_gas_density_kg_m3": pressure / (z * r_specific * fluid_temperature),
            "axial_effective_environment_k": effective_environment,
            "axial_exchange_exponent": axial_exponent,
            "surrogate_reynolds": reynolds,
            "surrogate_darcy_friction_factor": friction,
            "surrogate_upstream_absolute_pressure_pa": current_upstream,
            "upstream_pressure_ratio": pressure_ratio,
            "pressure_source_local_hour": source_hour["source_local_hour"] if source_hour else "",
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config.json").write_text(config_text, encoding="utf-8")
    forcing_path = output_dir / "forcing.csv"
    diagnostics_path = output_dir / "source_diagnostics.csv"
    for path, rows in ((forcing_path, forcing), (diagnostics_path, diagnostics)):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    shutil.copyfile(gas_assumptions_path, output_dir / "gas_assumptions_snapshot.json")
    used_sources = {key: entries[key] for key in paths}
    extra_output_names = []
    if pressure_hours:
        snapshot_path = output_dir / "pressure_hourly_snapshot.csv"
        with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(pressure_hours[0]))
            writer.writeheader()
            writer.writerows(pressure_hours)
        extra_output_names.append(snapshot_path.name)
        used_sources["ntsb_pressure_profile"] = {
            "channel_id": pressure_profile["channel_id"],
            "source_url": pressure_profile["source_url"],
            "source_pdf_sha256": pressure_profile["source_pdf_sha256"],
            "pressure_csv_sha256": pressure_profile["pressure_csv_sha256"],
            "channel_manifest_sha256": pressure_profile["channel_manifest_sha256"],
        }
    quality_summary = {
        "all_source_hashes_verified": True,
        "consecutive_utc_weather_hours": len(weather),
        "rain_hours": sum(row["PRECTOTCORR"] > 0 for row in weather),
        "air_temperature_c_range": [min(row["T2M"] for row in weather),
                                     max(row["T2M"] for row in weather)],
        "surrogate_absolute_pressure_pa_range": [
            min(float(row["surrogate_absolute_pressure_pa"]) for row in diagnostics[1:]),
            max(float(row["surrogate_absolute_pressure_pa"]) for row in diagnostics[1:]),
        ],
        "internal_h_w_m2k_range": [min(float(row["h_inner_w_m2k"]) for row in forcing[1:]),
                                   max(float(row["h_inner_w_m2k"]) for row in forcing[1:])],
        "local_gas_temperature_c_range": [min(float(row["fluid_temperature_k"]) - 273.15 for row in forcing[1:]),
                                           max(float(row["fluid_temperature_k"]) - 273.15 for row in forcing[1:])],
        "external_h_w_m2k_range": [min(float(row["h_outer_w_m2k"]) for row in forcing[1:]),
                                   max(float(row["h_outer_w_m2k"]) for row in forcing[1:])],
    }
    output_manifest = {
        "schema_version": "2", "episode_id": prepared_id,
        "weather_source_key": episode,
        "weather_first_utc_hour": weather[0]["utc_hour"],
        "weather_last_utc_hour": weather[-1]["utc_hour"],
        "sample_count": len(forcing), "weather_interval_count": len(weather),
        "sample_period_s": 3600,
        "power_units": power_units, "gaslib_properties": gas,
        "trr_initial_pipe_state": initial,
        "initial_upstream_absolute_pressure_pa": p_upstream,
        "inferred_constant_upstream_pressure_pa": p_upstream if not pressure_hours else None,
        "pressure_profile": pressure_profile,
        "flow_profile": {"mode": "periodic_trr154_demand_surrogate", "period_s": 86400},
        "initial_state_calibrated_darcy_friction_factor": effective_friction,
        "friction_correction_ratio_to_haaland": effective_friction / f_ref,
        "trr_reference_reynolds": re_ref, "trr_reference_h_inner_w_m2k": h_ref,
        "source_files": used_sources,
        "quality_summary": quality_summary,
        "assumptions": assumptions,
        "field_lineage": {
            "direct_weather": ["ambient_temperature_k", "solar_w_m2"],
            "weather_derived": ["sky_temperature_k", "h_outer_w_m2k", "wet_drive"],
            "benchmark_derived_surrogate": (["h_inner_w_m2k"] if pressure_hours
                                             else ["pressure_pa", "h_inner_w_m2k"]),
            "external_ratio_and_benchmark_derived_surrogate": ["pressure_pa"] if pressure_hours else [],
            "benchmark_and_weather_derived_surrogate": ["fluid_temperature_k"],
            "benchmark_static": ["reference_temperature_k"],
            "scenario_assumed": ["solar_incidence", "drying_rate_multiplier",
                                  "wet_path_open", "bending_moment_nm"],
        },
        "model_scope": [
            "TRR154 sink-demand shape is repeated daily and scales the initial p_br52 flow; this is a surrogate, not a solved network state.",
            "The t=0 row initializes state; row k>0 applies the archived weather hour k-1 over (t[k-1], t[k]].",
            ("Pressure uses a single horizontal quasi-steady isothermal inlet-temperature pipe with fixed Z and initial-state-calibrated friction; upstream pressure follows the documented NTSB native-value ratio, not absolute NTSB pressure. GasLib source-node min/max are a benchmark envelope guard, not verified local pipe limits; no linepack or pressure-wave dynamics."
             if pressure_hours else
             "Pressure uses a single horizontal quasi-steady isothermal inlet-temperature pipe with fixed Z, initial-state-calibrated friction and fixed upstream pressure; no linepack or pressure-wave dynamics."),
            "Local gas temperature optionally uses a quasi-steady exponential axial heat-exchange surrogate over an assumed effective exposure length; one Saudi weather cell stands for the whole exposed route, without travel delay, axial storage or Joule-Thomson cooling. This temperature is not coupled back into the pressure surrogate.",
            "TRR154 pressure is treated as absolute for EOS and reduced by assumed external pressure for wall stress; pressure-reference convention is not independently verified.",
            "GasLib gas record supplies molar mass and gas temperature, not a measured composition or Saudi operating history.",
            "p_br52 joins node_52 to node_53, not source node_1; the three GasLib source nodes share the same reference gas properties. The GasLib pipe heatTransferCoefficient is archived but not used because the local Saudi-weather exposure is a different hypothetical scenario.",
            "Wind-height, solar-incidence, gas transport properties and steel/patch parameters are research assumptions.",
            "No gas leak, local wall loss, crack, scratch or saddle transfer calibration is inferred.",
        ],
        "split_constraints": [
            "Keep overlapping weather source windows and their scenario branches in the same split.",
            "Keep all NTSB Cheyenne channels/windows/transplants together by source_group_id; different weather does not make reused pressure history independent.",
        ],
        "training_ready": False,
        "output_sha256": {name: _sha256(output_dir / name) for name in
                          ["config.json", "forcing.csv", "source_diagnostics.csv",
                           "gas_assumptions_snapshot.json", *extra_output_names]},
    }
    (output_dir / "reference_manifest.json").write_text(
        json.dumps(output_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return output_manifest
