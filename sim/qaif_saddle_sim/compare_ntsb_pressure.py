"""Audit public NTSB pressure against Qaif's present *forcing*, not saddle output.

The sources refer to different pipelines and sensors. Only dimensionless
within-channel variation is compared. Accident observations stay holdout data.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import statistics as stats
from collections import defaultdict
from pathlib import Path

EVENT = dt.datetime(2025, 9, 20, 23, 7)
NTSB_URL = "https://www.ntsb.gov/investigations/Pages/PLD25FR008.aspx"


def _read_scada(path: Path) -> list[tuple[dt.datetime, float]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [(dt.datetime.fromisoformat(row["source_local_time"]), float(row["source_value"]))
                for row in csv.DictReader(handle)]
    if not rows or rows != sorted(rows, key=lambda row: row[0]):
        raise ValueError(f"SCADA rows missing or out of time order: {path}")
    return rows


def _hourly_medians(rows: list[tuple[dt.datetime, float]]) -> list[tuple[dt.datetime, float]]:
    buckets: dict[dt.datetime, list[float]] = defaultdict(list)
    for moment, value in rows:
        buckets[moment.replace(minute=0, second=0)].append(value)
    return [(hour, stats.median(values)) for hour, values in sorted(buckets.items())]


def _metrics(hourly: list[tuple[dt.datetime, float]]) -> dict:
    values = [value for _, value in hourly]
    if len(values) < 2:
        raise ValueError("at least two hourly observations required")
    baseline = stats.median(values)
    deltas = [abs(later[1] - earlier[1]) / baseline * 100
              for earlier, later in zip(hourly, hourly[1:])
              if later[0] - earlier[0] == dt.timedelta(hours=1)]
    if not deltas:
        raise ValueError("no consecutive hourly pairs")
    deltas.sort()
    percentile_index = int(0.95 * (len(deltas) - 1))
    return {
        "hourly_bin_count": len(hourly),
        "consecutive_hour_pair_count": len(deltas),
        "median_native": baseline,
        "range_percent_of_median": (max(values) - min(values)) / baseline * 100,
        "median_abs_one_hour_change_percent": stats.median(deltas),
        "p95_abs_one_hour_change_percent": deltas[percentile_index],
        "max_abs_one_hour_change_percent": max(deltas),
    }


def _load_forcing(path: Path) -> list[tuple[dt.datetime, float]]:
    origin = dt.datetime(2024, 1, 1)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [(origin + dt.timedelta(seconds=int(row["timestamp_s"])), float(row["pressure_pa"]))
                for row in csv.DictReader(handle)]
    return rows


def _at(rows: list[tuple[dt.datetime, float]], when: dt.datetime) -> float:
    values = [value for moment, value in rows if moment == when]
    if len(values) != 1:
        raise ValueError(f"expected one reading at {when}, got {len(values)}")
    return values[0]


def run(root: Path = Path("outputs/ntsb_pressure_audit_v1"),
        forcing: Path = Path("outputs/sourced_v1_inland_desert_summer_2024/forcing.csv")) -> dict:
    verified = _read_scada(root / "verified_psig_57035/pressure.csv")
    west = _read_scada(root / "west_spill_1067220/pressure.csv")
    sim = _load_forcing(forcing)
    # Exclude the entire onset hour: its median would leak accident behavior
    # into the baseline, and the original exhibit only resolves whole minutes.
    normal_cut = EVENT.replace(minute=0)
    normal_verified = [row for row in verified if row[0] < normal_cut]
    normal_west = [row for row in west if row[0] < normal_cut]
    sim_hours = sim[:168]  # seven complete days; the final point closes the interval
    metrics = {
        "event_source_local_time": EVENT.isoformat(timespec="minutes"),
        "event_alignment": "NTSB preliminary report says 11:07 p.m. local; PDF timezone field absent; matching PDF timestamp is used without UTC conversion",
        "analysis_scope": "within-channel normalized pressure forcing variation; neither cross-pipeline absolute calibration nor saddle validation",
        "verified_psig_57035_pre_onset": _metrics(_hourly_medians(normal_verified)),
        "west_spill_1067220_pre_onset_unit_unspecified": _metrics(_hourly_medians(normal_west)),
        "qaif_gaslib_trr154_hourly_forcing": _metrics(sim_hours),
        "west_spill_event": {
            "value_at_23_05": _at(west, dt.datetime(2025, 9, 20, 23, 5)),
            "value_at_23_07": _at(west, EVENT),
            "value_at_23_09": _at(west, dt.datetime(2025, 9, 20, 23, 9)),
            "value_at_23_25": _at(west, dt.datetime(2025, 9, 20, 23, 25)),
        },
        "simulator_exact_24h_repeat_after_day_one": all(
            abs(sim_hours[i][1] - sim_hours[i - 24][1]) < 1e-8
            for i in range(48, len(sim_hours))),
        "simulator_initial_day_boundary_exception_count": sum(
            abs(sim_hours[i][1] - sim_hours[i - 24][1]) >= 1e-8
            for i in range(24, 48)),
        "source_forcing": str(forcing),
        "source_ntsb_exhibit": "qaif_saddle_sim/reference_data/ntsb_cheyenne_scada_7day_pressure.pdf",
        "ntsb_investigation": NTSB_URL,
        "training_or_calibration_used": False,
    }
    event = metrics["west_spill_event"]
    event["drop_23_05_to_23_07_percent"] = (event["value_at_23_07"] / event["value_at_23_05"] - 1) * 100
    event["drop_23_05_to_23_25_percent"] = (event["value_at_23_25"] / event["value_at_23_05"] - 1) * 100
    root.mkdir(parents=True, exist_ok=True)
    (root / "comparison.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    _plot(root / "comparison.png", normal_verified, normal_west, west, sim_hours)
    _write_report(root / "AUDIT.md", metrics)
    return metrics


def _plot(path: Path, verified, normal_west, west, sim):
    from PIL import Image, ImageDraw

    def panel(draw, rows, top, label, color, *, normalize=True):
        left, right, bottom = 140, 1150, top + 190
        values = [v for _, v in rows]
        base = stats.median(values) if normalize else 0
        mapped = [(v / base - 1) * 100 if normalize else v for v in values]
        lo, hi = min(mapped), max(mapped)
        pad = max((hi - lo) * 0.1, 0.01)
        lo, hi = lo - pad, hi + pad
        start, end = rows[0][0], rows[-1][0]
        span = (end - start).total_seconds()
        points = [(left + int((t - start).total_seconds() / span * (right - left)),
                   bottom - int((value - lo) / (hi - lo) * 140))
                  for (t, _), value in zip(rows, mapped)]
        draw.text((left, top), label, fill="black")
        draw.line((left, bottom, right, bottom), fill="#777777", width=1)
        draw.line((left, top + 50, left, bottom), fill="#777777", width=1)
        draw.text((20, top + 55), f"{hi:.2f}", fill="black")
        draw.text((20, bottom - 20), f"{lo:.2f}", fill="black")
        draw.text((left, bottom + 5), str(start.date()), fill="black")
        draw.text((right - 75, bottom + 5), str(end.date()), fill="black")
        if len(points) > 1:
            draw.line(points, fill=color, width=2)

    canvas = Image.new("RGB", (1200, 805), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((140, 15), "Independent pressure audit: percent deviation from each channel median", fill="black")
    for rows, top, label, color in (
        (verified, 55, "NTSB channel 57035: PSIG, before onset", "#1d4ed8"),
        (normal_west, 295, "NTSB West Spill: source unit unspecified, before onset", "#0f766e"),
        (sim, 535, "Qaif GasLib/TRR154 hourly surrogate forcing", "#b45309"),
    ):
        panel(draw, rows, top, label, color)
    canvas.save(path)

    nearby = [row for row in west if dt.datetime(2025, 9, 20, 22, 30) <= row[0]
              <= dt.datetime(2025, 9, 21, 0, 30)]
    canvas = Image.new("RGB", (1200, 320), "white")
    draw = ImageDraw.Draw(canvas)
    panel(draw, nearby, 30, "West Spill around 23:07 detection; original unit omitted", "#0f766e", normalize=False)
    x_event = 140 + int((EVENT - nearby[0][0]).total_seconds()
                        / (nearby[-1][0] - nearby[0][0]).total_seconds() * 1010)
    draw.line((x_event, 80, x_event, 220), fill="red", width=2)
    draw.text((x_event + 5, 80), "23:07", fill="red")
    canvas.save(path.with_name("event_window.png"))


def _write_report(path: Path, data: dict):
    a = data["verified_psig_57035_pre_onset"]
    b = data["west_spill_1067220_pre_onset_unit_unspecified"]
    c = data["qaif_gaslib_trr154_hourly_forcing"]
    e = data["west_spill_event"]
    text = f"""# Independent NTSB pressure audit of Qaif forcing

## Finding

The current Qaif *pressure forcing* is too regular to stand in for measured operational pressure. After its first day, the 24-hour sequence repeats exactly; the first day differs at one boundary sample. The real channels show larger and less regular pre-onset variation. This is a mismatch in forcing realism, **not** a validation or falsification of the saddle sensor, leak classifier, or defect localization model.

| Series | Hourly bins | Range / own median | Median abs(Δ1h) / median | 95th percentile abs(Δ1h) / median |
|---|---:|---:|---:|---:|
| NTSB channel 57035, explicit PSIG | {a['hourly_bin_count']} | {a['range_percent_of_median']:.3f}% | {a['median_abs_one_hour_change_percent']:.3f}% | {a['p95_abs_one_hour_change_percent']:.3f}% |
| NTSB West Spill 1067220, unit omitted | {b['hourly_bin_count']} | {b['range_percent_of_median']:.3f}% | {b['median_abs_one_hour_change_percent']:.3f}% | {b['p95_abs_one_hour_change_percent']:.3f}% |
| Qaif GasLib/TRR154 surrogate forcing | {c['hourly_bin_count']} | {c['range_percent_of_median']:.3f}% | {c['median_abs_one_hour_change_percent']:.3f}% | {c['p95_abs_one_hour_change_percent']:.3f}% |

Hour bins are medians of available original samples; one-hour differences use **only consecutive occupied bins**. NTSB bins after 23:00 on 20 September 2025 are excluded from these pre-onset metrics. The pre-onset period has **not** been independently certified fault-free or free from compressor/control actions, so it is an external plausibility check, not a calibrated normal-operation distribution. The simulator series uses seven complete days. Different pipeline assets, channels and dates are not aligned point-for-point or compared in absolute pressure.

At the West Spill channel, the original table reads {e['value_at_23_05']} at 23:05, {e['value_at_23_07']} at 23:07 and {e['value_at_23_25']} at 23:25: changes of {e['drop_23_05_to_23_07_percent']:.2f}% and {e['drop_23_05_to_23_25_percent']:.2f}% relative to 23:05. Its numeric unit is **not printed in this PDF**, so these are native values and ratios only. The [NTSB preliminary account]({NTSB_URL}) independently reports detection at about 11:07 p.m. local and a pre-incident operating pressure of 810 psig; this corroborates the event timing and approximate magnitude, but is not channel-specific unit metadata.

## Provenance and use

- Original: [NTSB Cheyenne SCADA Seven Day Pressure Data]({'https://data.ntsb.gov/Docket/Document/docBLOB?FileExtension=pdf&FileName=Cheyenne+SCADA+Seven+Day+Pressure+Data+1272026-Rel.pdf&ID=20831703'}) in [docket PLD25FR008]({'https://data.ntsb.gov/Docket?ProjectID=201060'}). Local file hash: `5d31cf25e14ad24859674034c9eb918f0d57cf2beb57831f76bd40cca277a75a` (SHA-256). The 344-page exhibit yielded 27,136 rows across nine channels with no rejected table lines.
- Retained two channels: verified PSIG point 57035 (1,448 original readings), and West Spill pressure point 1067220 (5,930 original readings, unit absent). Manifests retain record IDs, source pages, gap diagnostics, and hashes.
- The PDF does not specify a timezone. The NTSB account calls incident times local; timestamp alignment to the 23:07 row is therefore corroborative, without a UTC conversion.
- This accident is a **held-out stress test** only. It has not been used to tune or train the simulator. It is not a saddle signal, a pre-failure crack label, or proof of early detection. The PDF's minute-resolution SCADA history also cannot validate sub-minute rupture physics.
- Reproducibility note: the official NTSB PDF was fetched with TLS certificate checking bypassed after local Windows TLS failures; its source URL and local SHA-256 are retained. A separate trusted download can verify the bytes by hash.

## Simulator decision

Keep the existing GasLib/TRR154 mean-pressure envelope as a **surrogate**, but do not call its repeated 24-hour variation field-calibrated. Before any training dataset is finalized, replace or augment that pressure schedule with a documented operating variability model from multiple independent normal-operation sources. Keep the NTSB rupture window outside the training and parameter-selection set, then repeat this audit. Without real saddle transfer measurements, SCADA pressure alone cannot determine the saddle's defect signatures.
"""
    stress_path = path.parent / "holdout_stress/stress_report.json"
    if stress_path.is_file():
        stress = json.loads(stress_path.read_text(encoding="utf-8"))
        text += f"""
## Held-out pressure-response check

The 23:05–23:25 West Spill source ratio was mapped to the GasLib surrogate's initial pressure and compared with a **constant-pressure control** using the same config, weather inputs, timestamps and random seed. At 23:25 the mapped pressure was {stress['pressure_drop_percent_at_end']:.2f}% lower, and the simulator's latent hoop strain differed from control by {stress['end_hoop_strain_difference_microstrain']:.2f} microstrain. This checks the implemented pressure–strain response, which follows the model's own equation. It does **not** measure a saddle, classify a leak, calibrate sensitivity, or demonstrate advance warning. The event window remains held out from training and parameter selection. See `holdout_stress/stress_report.json` and both input/output snapshots.
"""
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: value for key, value in result.items() if key.endswith("forcing")
                      or key.startswith("simulator_") or key == "west_spill_event"}, indent=2))
