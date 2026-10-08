"""Verified pre-onset NTSB pressure ratios for a declared surrogate experiment.

No absolute pressure or simultaneous weather/flow is inferred from this source.
Source-local clock hours are paired by elapsed position with archived weather.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

NTSB_HOLDOUT_START = dt.datetime(2025, 9, 20, 23)
NTSB_PDF_SHA256 = "5d31cf25e14ad24859674034c9eb918f0d57cf2beb57831f76bd40cca277a75a"
NTSB_CHANNEL_UNITS = {"57035": "PSIG", "1067220": "unspecified in PDF"}
PRESSURE_MODES = ("periodic_benchmark_surrogate", "ntsb_relative_upstream")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_ntsb_pressure_profile(channel_dir: str | Path, source_pdf: str | Path,
                               start_local: str, hours: int) -> tuple[list[dict], dict]:
    """Return consecutive hourly medians/ratios; reject missing hours, no filling.

    Both channels use native numeric ratios, including the explicit PSIG channel.
    Multiplying an absolute GasLib inlet pressure by a gauge/native source ratio
    is an assumed transfer of variability, not a pressure unit conversion.
    """
    if not isinstance(hours, int) or isinstance(hours, bool) or hours < 1:
        raise ValueError("pressure window hours must be a positive integer")
    try:
        start = dt.datetime.strptime(start_local, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError) as exc:
        raise ValueError("pressure start must be source-local YYYY-MM-DD HH:00") from exc
    if start.minute != 0:
        raise ValueError("pressure start must be on a source-local whole hour")
    end = start + dt.timedelta(hours=hours)
    if end > NTSB_HOLDOUT_START:
        raise ValueError("pressure window overlaps the held-out incident period (from 2025-09-20 23:00)")

    channel_dir, source_pdf = Path(channel_dir), Path(source_pdf)
    manifest_path, csv_path = channel_dir / "manifest.json", channel_dir / "pressure.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("source_pdf_sha256") != NTSB_PDF_SHA256
            or not source_pdf.is_file() or _sha256(source_pdf) != NTSB_PDF_SHA256):
        raise ValueError("NTSB original PDF hash mismatch")
    csv_hash = _sha256(csv_path)
    if csv_hash != manifest.get("pressure_csv_sha256"):
        raise ValueError("NTSB pressure CSV hash mismatch")
    channel = manifest.get("channel_id")
    if channel not in NTSB_CHANNEL_UNITS or manifest.get("unit_source") != NTSB_CHANNEL_UNITS[channel]:
        raise ValueError("unsupported NTSB channel or inconsistent unit metadata")

    # Collapse records sharing one minute before aggregation, so duplicate
    # minute rows do not receive disproportionate weight in the hourly median.
    minute_values: dict[dt.datetime, list[float]] = {}
    pages: dict[dt.datetime, set[int]] = {}
    selected_count = 0
    previous_time = None
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"source_local_time", "source_value", "source_page", "source_unit_text"} <= set(reader.fieldnames or ()):
            raise ValueError("NTSB pressure CSV lacks required columns")
        for row in reader:
            time = dt.datetime.strptime(row["source_local_time"], "%Y-%m-%d %H:%M")
            if previous_time is not None and time < previous_time:
                raise ValueError("NTSB pressure timestamps are not sorted")
            previous_time = time
            if not start <= time < end:
                continue
            value = float(row["source_value"])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"nonpositive or nonfinite NTSB source pressure at {time}")
            expected_row_unit = "PSIG" if channel == "57035" else ""
            if row["source_unit_text"] != expected_row_unit:
                raise ValueError("NTSB row unit differs from channel metadata")
            page = int(row["source_page"])
            if not 1 <= page <= manifest["source_pdf_page_count"]:
                raise ValueError("NTSB source page outside original PDF")
            minute_values.setdefault(time, []).append(value)
            pages.setdefault(time, set()).add(page)
            selected_count += 1

    bins: dict[dt.datetime, list[tuple[dt.datetime, float]]] = {}
    for time, values in minute_values.items():
        bins.setdefault(time.replace(minute=0), []).append((time, statistics.median(values)))
    hourly = []
    for index in range(hours):
        hour = start + dt.timedelta(hours=index)
        samples = bins.get(hour, [])
        if not samples:
            raise ValueError(f"missing NTSB pressure hour: {hour:%Y-%m-%d %H:%M}; no interpolation allowed")
        times = [t for t, _ in samples]
        hourly.append({
            "source_local_hour": hour.strftime("%Y-%m-%d %H:%M"),
            "source_native_hourly_median": statistics.median(v for _, v in samples),
            "source_unique_minute_count": len(samples),
            "source_first_sample_local": min(times).strftime("%Y-%m-%d %H:%M"),
            "source_last_sample_local": max(times).strftime("%Y-%m-%d %H:%M"),
            "source_pages": ",".join(str(p) for p in sorted(set().union(*(pages[t] for t in times)))),
        })
    anchor = hourly[0]["source_native_hourly_median"]
    for row in hourly:
        row["upstream_pressure_ratio"] = row["source_native_hourly_median"] / anchor
    times = sorted(minute_values)
    # Include window edges in the gap audit; occupied bins alone do not assert
    # uniformly sampled or complete time coverage within every hour.
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    edge_gaps = [(times[0] - start).total_seconds() / 60,
                 (end - times[-1]).total_seconds() / 60]
    profile = {
        "mode": "ntsb_relative_upstream",
        "channel_id": channel, "channel_name": manifest["channel_name"],
        "source_url": manifest["source_url"],
        "source_docket_url": manifest["source_docket_url"],
        "source_group_id": "ntsb_cheyenne_PLD25FR008",
        "source_pdf_sha256": NTSB_PDF_SHA256,
        "pressure_csv_sha256": csv_hash,
        "channel_manifest_sha256": _sha256(manifest_path),
        "native_unit": manifest["unit_source"],
        "absolute_pressure_conversion_used": False,
        "source_timezone": "unspecified; source-local times retained, no UTC conversion",
        "window_start_local_inclusive": start.strftime("%Y-%m-%d %H:%M"),
        "window_end_local_exclusive": end.strftime("%Y-%m-%d %H:%M"),
        "heldout_start_local_inclusive": NTSB_HOLDOUT_START.strftime("%Y-%m-%d %H:%M"),
        "hour_count": hours, "selected_record_count": selected_count,
        "selected_unique_minute_count": len(times),
        "duplicate_minute_record_count": selected_count - len(times),
        "max_internal_sample_gap_minutes": max(gaps, default=0),
        "edge_gap_minutes": edge_gaps,
        "max_gap_including_edges_minutes": max(gaps + edge_gaps),
        "missing_hour_count": 0, "gap_fill": "none; empty hour rejected",
        "aggregation": "median of per-minute medians in [hour, hour+1h); not a time-weighted mean",
        "normalization": "divide by first selected hourly native median",
        "anchor_source_native_value": anchor,
        "mapping": "p_up_abs(t) = GasLib/TRR154 initial inlet absolute pressure * source_native_ratio(t)",
        "time_alignment": "elapsed-hour pairing with NASA weather from a different year/site; no simultaneous measurement claimed",
        "flow_source": "TRR154 periodic demand surrogate; no NTSB flow inferred",
        "source_download_tls_validation": manifest.get("source_download_tls_validation"),
        "intended_use": "pre-onset variability sensitivity/replay; not certified healthy operation or a training distribution",
        "training_ready": False,
    }
    return hourly, profile
