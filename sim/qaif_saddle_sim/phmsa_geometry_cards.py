"""Extract three auditable incident geometry cards from PHMSA's official ZIP.

Reported incidents are mechanism/geometry examples, not a failure prior,
normal-operation sample, saddle transfer calibration, or training signal.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

ZIP_URL = ("https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_statistics/pipeline/"
           "incident_gas_transmission_gathering_jan2010_present.zip")
SELECTED = {
    "20180059": {
        "card_id": "PH-01", "mechanism": "reported external corrosion / pinhole",
        "evidence_note": "Reported aboveground pipe; narrative says pinhole was found during an anomaly investigation. No precursor sensor trace.",
    },
    "20250024": {
        "card_id": "PH-02", "mechanism": "reported stress corrosion cracking",
        "evidence_note": "Buried pipe; narrative cites laboratory conclusion involving residual bend stress and mildly corrosive environment. No saddle response.",
    },
    "20250026": {
        "card_id": "PH-03", "mechanism": "reported girth-weld construction flaw",
        "evidence_note": "Buried pipe; narrative cites metallurgical finding of insufficient penetration and misalignment. No precursor strain trace.",
    },
}
FIELDS = [
    "REPORT_NUMBER", "REPORT_TYPE", "IYEAR", "LOCAL_DATETIME", "INCIDENT_AREA_TYPE",
    "INCIDENT_AREA_SUBTYPE", "SYSTEM_PART_INVOLVED", "MATERIAL_INVOLVED", "PIPE_TYPE",
    "WELD_SUBTYPE", "PIPE_DIAMETER", "PIPE_WALL_THICKNESS", "PIPE_SMYS",
    "PIPE_COATING_TYPE", "ACCIDENT_PSIG", "MOP_PSIG", "CAUSE", "CAUSE_DETAILS",
    "LEAK_TYPE", "VISUAL_EXAM_RESULTS",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path = Path("qaif_saddle_sim/reference_data/phmsa_incident_gas_transmission_gathering_jan2010_present.zip"),
          output: Path = Path("qaif_saddle_sim/phmsa_geometry_cards.json")) -> dict:
    with zipfile.ZipFile(source) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".txt"))
        reader = csv.DictReader(io.TextIOWrapper(archive.open(member), encoding="cp1252", newline=""),
                                delimiter="\t")
        records = list(reader)
    if len(records) < 1000 or not set(FIELDS).issubset(reader.fieldnames or []):
        raise ValueError("PHMSA file schema/size is unexpected")
    selected = {row["REPORT_NUMBER"]: row for row in records if row["REPORT_NUMBER"] in SELECTED}
    if len(selected) != len(SELECTED):
        raise ValueError("one or more selected PHMSA reports are missing")
    cards = []
    for number, definition in SELECTED.items():
        row = selected[number]
        if "FINAL" not in row["REPORT_TYPE"] or row["MATERIAL_INVOLVED"] != "CARBON STEEL":
            raise ValueError(f"report {number} lost final/steel status")
        if not all(row[key].strip() for key in ("PIPE_DIAMETER", "PIPE_WALL_THICKNESS",
                                                 "ACCIDENT_PSIG", "MOP_PSIG", "CAUSE_DETAILS")):
            raise ValueError(f"report {number} lost essential fields")
        card = {"card_id": definition["card_id"], "mechanism": definition["mechanism"],
                "evidence_note": definition["evidence_note"],
                "reported_fields": {key: row[key] for key in FIELDS},
                "narrative_present": bool(row["NARRATIVE"].strip()),
                "use": "geometry/mechanism plausibility only; never fault waveform or incidence prior",
                "training_ready": False}
        cards.append(card)
    result = {
        "schema_version": "1", "source_url": ZIP_URL,
        "source_zip_sha256": sha256(source), "source_member": member,
        "row_count_in_source": len(records), "selected_card_count": len(cards),
        "selection_note": "explicit report IDs chosen for one aboveground corrosion and two buried failure analogues; not random or representative",
        "field_definition_pdf": "qaif_saddle_sim/reference_data/phmsa_incident_data_fields.pdf",
        "card_training_ready": False, "cards": cards,
    }
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    report = build()
    print(json.dumps({"row_count_in_source": report["row_count_in_source"],
                      "selected_card_count": report["selected_card_count"],
                      "source_zip_sha256": report["source_zip_sha256"]}, indent=2))
