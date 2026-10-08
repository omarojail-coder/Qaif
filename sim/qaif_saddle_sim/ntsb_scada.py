"""Extract and audit timestamped pressure readings from one NTSB docket PDF.

The PDF is a public accident-investigation exhibit. Its channels are remote
SCADA points, not Qaif saddle measurements or a representative normal sample.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

SOURCE_URL = (
    "https://data.ntsb.gov/Docket/Document/docBLOB?FileExtension=pdf&"
    "FileName=Cheyenne+SCADA+Seven+Day+Pressure+Data+1272026-Rel.pdf&ID=20831703"
)
SOURCE_DOCKET = "https://data.ntsb.gov/Docket?ProjectID=201060"
PSI_TO_PA = 6894.757293168


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_pdf(path: str | Path) -> tuple[list[dict], dict]:
    path = Path(path)
    rows: list[dict] = []
    rejected = Counter()
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            page_words = page.extract_words()
            headers = {word["text"]: word["x0"] for word in page_words
                       if word["text"] in {"Id", "RecordId", "~Time", "FormattedValue"}
                       and word["top"] < 90}
            if len(headers) != 4:
                rejected["page_without_complete_header"] += 1
                continue
            cutpoints = [headers[key] - 5 for key in ("Id", "RecordId", "~Time", "FormattedValue")]
            groups: dict[int, list[dict]] = defaultdict(list)
            for word in page_words:
                groups[round(word["top"])].append(word)
            for words in groups.values():
                columns = [[], [], [], [], []]
                for word in sorted(words, key=lambda item: item["x0"]):
                    x = word["x0"]
                    column = next((i for i, boundary in enumerate(cutpoints) if x < boundary), 4)
                    columns[column].append(word["text"])
                name, sensor_id, record_id, when, value = (" ".join(items) for items in columns)
                if name == "FullName":
                    continue
                if not name or not sensor_id or not when or not value:
                    rejected["missing_columns"] += 1
                    continue
                try:
                    moment = dt.datetime.strptime(when, "%m/%d/%Y %H:%M")
                    tokens = value.split()
                    numeric = float(tokens[0])
                    if not math.isfinite(numeric):
                        raise ValueError("nonfinite")
                except (ValueError, IndexError):
                    rejected["unparsed_value_or_time"] += 1
                    continue
                unit = " ".join(tokens[1:])
                rows.append({
                    "source_page": page_number,
                    "channel_name": name,
                    "sensor_id": sensor_id,
                    "record_id": record_id,
                    "source_local_time": moment.strftime("%Y-%m-%d %H:%M"),
                    "source_value": numeric,
                    "source_unit_text": unit,
                })
    return rows, {"page_count": page_count, "parsed_count": len(rows),
                  "rejected_line_counts": dict(rejected),
                  "channel_counts": dict(Counter(row["sensor_id"] for row in rows))}


def _export_selected(source: Path, all_rows: list[dict], parse_report: dict,
                     sensor_id: str, output_dir: Path) -> dict:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    selected = [row for row in all_rows if row["sensor_id"] == sensor_id]
    if not selected:
        raise ValueError(f"sensor ID {sensor_id} is not in the PDF")
    names = {row["channel_name"] for row in selected}
    units = {row["source_unit_text"] for row in selected}
    if len(names) != 1 or len(units) != 1 or next(iter(units)) not in {"PSIG", ""}:
        raise ValueError(f"selected channel has inconsistent name/units: {names}, {units}")
    unit = next(iter(units))
    selected.sort(key=lambda row: (row["source_local_time"], row["record_id"]))
    times = [dt.datetime.strptime(row["source_local_time"], "%Y-%m-%d %H:%M") for row in selected]
    if len(selected) != len({row["record_id"] for row in selected}):
        raise ValueError("selected channel has duplicate record IDs")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "pressure.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["source_local_time", "elapsed_s", "source_record_id", "source_value",
                  "source_unit_text", "pressure_gauge_pa", "source_page"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row, moment in zip(selected, times):
            writer.writerow({
                "source_local_time": row["source_local_time"],
                "elapsed_s": int((moment - times[0]).total_seconds()),
                "source_record_id": row["record_id"],
                "source_value": row["source_value"],
                "source_unit_text": unit,
                "pressure_gauge_pa": row["source_value"] * PSI_TO_PA if unit == "PSIG" else "",
                "source_page": row["source_page"],
            })
    gaps_minutes = [(later - earlier).total_seconds() / 60 for earlier, later in zip(times, times[1:])]
    manifest = {
        "schema_version": "1", "source_url": SOURCE_URL,
        "source_docket_url": SOURCE_DOCKET,
        "source_pdf_sha256": sha256(source),
        "source_pdf_page_count": parse_report["page_count"],
        "pdf_parse_report": parse_report,
        "channel_id": sensor_id,
        "channel_name": next(iter(names)),
        "unit_source": unit or "unspecified in PDF",
        "unit_output": "Pa gauge" if unit == "PSIG" else None,
        "sample_count": len(selected),
        "duplicate_minute_timestamp_count": len(times) - len(set(times)),
        "first_source_local_time": selected[0]["source_local_time"],
        "last_source_local_time": selected[-1]["source_local_time"],
        "timezone": "not specified in this PDF; no UTC conversion applied",
        "gap_minutes_max": max(gaps_minutes) if gaps_minutes else 0,
        "gap_minutes_median": sorted(gaps_minutes)[len(gaps_minutes) // 2] if gaps_minutes else 0,
        "source_download_tls_validation": "bypassed locally after Windows TLS failure; official NTSB URL and SHA-256 retained",
        "interpretation": "remote SCADA pressure; not a saddle signal or defect class label",
        "training_ready": False,
        "pressure_csv_sha256": sha256(csv_path),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def export_channels(path: str | Path, channels: dict[str, str | Path]) -> dict[str, dict]:
    source = Path(path)
    rows, parse_report = parse_pdf(source)
    return {sensor_id: _export_selected(source, rows, parse_report, sensor_id, Path(destination))
            for sensor_id, destination in channels.items()}


def export_channel(path: str | Path, sensor_id: str, output_dir: str | Path) -> dict:
    return export_channels(path, {sensor_id: output_dir})[sensor_id]
