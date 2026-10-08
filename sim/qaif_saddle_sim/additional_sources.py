"""Offline archival and strict loading of an additional benchmark/pressure source."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

from .evidence_registry import sha256
from .reference_episode import GAS_NS, _checked_file, _value

NATIVE_UNIT = "unspecified in printed historical table; native ratio only"
SOURCE_GROUP = "ntsb_san_bruno_DCA10MP008"
CUTOFF = dt.datetime(2010,9,9)


def archive_sources(source_dir, inventory_path, output_dir):
    """Copy the TLS-verified source files and extract the first historical week."""
    from pypdf import PdfReader
    source_dir, out = Path(source_dir), Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("additional source archive already exists")
    inventory=json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    for name in ("GasLibE-39-v1.zip","san_bruno_pressure_history.pdf","mit_pressure_vessels.pdf"):
        meta=inventory[name]
        if meta.get("tls_certificate_validation") is not True or sha256(source_dir/name)!=meta["sha256"]:
            raise ValueError("source download/hash verification failed")
    reader=PdfReader(source_dir/"san_bruno_pressure_history.pdf")
    start,end=dt.datetime(2002,1,1),dt.datetime(2002,1,8)
    extracted=[]
    # The complete PDF is archived, but no post-incident table is imported.
    for i in range(2,6):
        text=reader.pages[i].extract_text()
        if "MMT_PT0083" not in text or "NMA_PT0030" not in text:
            raise ValueError("historical pressure table header does not match")
        for line in text.splitlines():
            if not re.match(r"^\d{2}/\d{2}/\d{2} \d{2}:\d{2}\b",line):
                continue
            fields=line.split()
            time=dt.datetime.strptime(" ".join(fields[:2]),"%m/%d/%y %H:%M")
            if not start<=time<end:
                continue
            if len(fields)!=8:
                raise ValueError("ambiguous/missing pressure columns in selected source row")
            values=[float(v) for v in fields[2:]]
            if any(not math.isfinite(v) or v<=0 for v in values):
                raise ValueError("invalid selected pressure table row")
            extracted.append({"source_local_time":time.strftime("%Y-%m-%d %H:%M"),
                              "source_value":values[4],"source_page":i+1,
                              "source_unit_text":""})
    times=[dt.datetime.fromisoformat(r["source_local_time"]) for r in extracted]
    if times!=[start+dt.timedelta(hours=i) for i in range(168)]:
        raise ValueError("selected historical week is not unique/consecutive/complete")
    out.mkdir(parents=True)
    entries={}
    for name,meta in inventory.items():
        shutil.copyfile(source_dir/name,out/name)
        entries[name]={**meta,"path":name}
    bundle=ZipFile(out/"GasLibE-39-v1.zip")
    net=next(n for n in bundle.namelist() if n.endswith(".net"))
    # Do not extract arbitrary archive paths. Only the inspected XML member.
    network_name="GasLibE-39.net"
    (out/network_name).write_bytes(bundle.read(net))
    entries[network_name]={"path":network_name,"sha256":sha256(out/network_name),
                           "parent_zip_sha256":entries["GasLibE-39-v1.zip"]["sha256"],
                           "archive_member":net,"url":"https://zenodo.org/records/22141135",
                           "kind":"artificial stationary benchmark, not measured operation",
                           "citation":"F. Hennings, Modeling and solving real-world transient gas network transport problems using mathematical programming, TU Berlin, 2023",
                           "citation_url":"https://doi.org/10.14279/depositonce-18303"}
    csv_path=out/"san_bruno_pressure.csv"
    with csv_path.open("w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(extracted[0])); writer.writeheader();writer.writerows(extracted)
    manifest={"schema_version":"1","source_group_id":SOURCE_GROUP,
              "source_pdf":"san_bruno_pressure_history.pdf","source_pdf_sha256":sha256(out/"san_bruno_pressure_history.pdf"),
              "pressure_csv":"san_bruno_pressure.csv","pressure_csv_sha256":sha256(csv_path),
              "source_pdf_page_count":len(reader.pages),"source_url":entries["san_bruno_pressure_history.pdf"]["url"],
              "channel_id":"NMA_PT0030","channel_name":"MRTIN-STA L132 U/S PRESS",
              "native_unit":NATIVE_UNIT,"source_timezone":"unspecified; source-local clock",
              "source_week_start_local":"2002-01-01 00:00","source_week_end_local_exclusive":"2002-01-08 00:00",
              "holdout_start_local_inclusive":CUTOFF.strftime("%Y-%m-%d %H:%M"),
              "source_row_count":168,"source_pages":sorted({r["source_page"] for r in extracted}),
              "certified_healthy_operation":False,"training_ready":False,"entries":entries}
    (out/"source_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest


def load_native_hourly_archive(directory, start_local, hours):
    directory=Path(directory)
    meta=json.loads((directory/"source_manifest.json").read_text(encoding="utf-8"))
    if (meta.get("schema_version")!="1" or meta.get("source_group_id")!=SOURCE_GROUP
            or meta.get("native_unit")!=NATIVE_UNIT or meta.get("training_ready") is not False):
        raise ValueError("unsupported additional pressure archive metadata")
    # Restrict file names and cutoff to this explicitly reviewed archive.
    if meta.get("source_pdf")!="san_bruno_pressure_history.pdf" or meta.get("pressure_csv")!="san_bruno_pressure.csv":
        raise ValueError("unexpected pressure archive path")
    for name,key in ((meta["source_pdf"],"source_pdf_sha256"),(meta["pressure_csv"],"pressure_csv_sha256")):
        if sha256(directory/name)!=meta[key]:
            raise ValueError("additional pressure source hash mismatch")
    if not isinstance(hours,int) or isinstance(hours,bool) or hours<1:
        raise ValueError("pressure hours must be a positive integer")
    start=dt.datetime.strptime(start_local,"%Y-%m-%d %H:%M");end=start+dt.timedelta(hours=hours)
    if start.minute or end>CUTOFF:
        raise ValueError("source hour alignment/incident cutoff invalid")
    with (directory/meta["pressure_csv"]).open(encoding="utf-8",newline="") as handle:
        rows=list(csv.DictReader(handle))
    lookup={}
    previous=None
    for row in rows:
        time=dt.datetime.fromisoformat(row["source_local_time"])
        if previous is not None and time<=previous:
            raise ValueError("duplicate/non-increasing historical pressure hour")
        previous=time
        value=float(row["source_value"])
        if not math.isfinite(value) or value<=0 or row["source_unit_text"]!="":
            raise ValueError("invalid native pressure/unit")
        if not 1<=int(row["source_page"])<=meta["source_pdf_page_count"]:
            raise ValueError("source page outside PDF")
        lookup[time]=row
    result=[]
    for i in range(hours):
        time=start+dt.timedelta(hours=i)
        if time not in lookup:
            raise ValueError("missing historical pressure hour; interpolation forbidden")
        row=lookup[time]
        result.append({"source_local_hour":row["source_local_time"],
                       "source_native_hourly_median":float(row["source_value"]),
                       "source_unique_minute_count":1,"source_pages":row["source_page"]})
    anchor=result[0]["source_native_hourly_median"]
    for row in result: row["upstream_pressure_ratio"]=row["source_native_hourly_median"]/anchor
    profile={"mode":"archived_native_relative_upstream","channel_id":meta["channel_id"],
             "channel_name":meta["channel_name"],"source_group_id":SOURCE_GROUP,
             "source_url":meta["source_url"],"source_pdf_sha256":meta["source_pdf_sha256"],
             "pressure_csv_sha256":meta["pressure_csv_sha256"],"channel_manifest_sha256":sha256(directory/"source_manifest.json"),
             "native_unit":NATIVE_UNIT,"absolute_pressure_conversion_used":False,
             "window_start_local_inclusive":start.strftime("%Y-%m-%d %H:%M"),
             "window_end_local_exclusive":end.strftime("%Y-%m-%d %H:%M"),
             "hour_count":hours,"missing_hour_count":0,"aggregation":"original printed hourly value; no averaging/interpolation",
             "source_timezone":meta["source_timezone"],"training_ready":False}
    return result,profile


def load_extra_asset(directory):
    directory=Path(directory)
    meta=json.loads((directory/"source_manifest.json").read_text(encoding="utf-8"))
    network=_checked_file(directory,meta["entries"]["GasLibE-39.net"])
    root=ET.parse(network).getroot()
    pipe=root.find('.//g:pipe[@id="P_NW_1"]',GAS_NS)
    source=root.find('.//g:source[@id="E_NW"]',GAS_NS)
    if pipe is None or source is None:
        raise ValueError("additional benchmark pipe/source missing")
    return {"asset_id":"gaslibe39_P_NW_1_surrogate","benchmark_network":"GasLibE-39",
            "pipe_id":"P_NW_1","source_id":"E_NW","network_sha256":sha256(network),
            "inner_diameter_m":_value(pipe,"g:diameter",GAS_NS,"mm")/1000,
            "pipe_length_m":_value(pipe,"g:length",GAS_NS,"km")*1000,
            "roughness_m":_value(pipe,"g:roughness",GAS_NS,"mm")/1000,
            "gas_temperature_k":_value(source,"g:gasTemperature",GAS_NS,"Celsius")+273.15,
            "molar_mass_kg_mol":_value(source,"g:molarMass",GAS_NS,"kg_per_kmol")/1000,
            "source_pressure_min_pa":_value(source,"g:pressureMin",GAS_NS,"bar")*1e5,
            "source_pressure_max_pa":_value(source,"g:pressureMax",GAS_NS,"bar")*1e5,
            "measured_pipeline":False,"training_ready":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir",required=True);parser.add_argument("--inventory",required=True)
    parser.add_argument("--out",required=True);args=parser.parse_args()
    manifest=archive_sources(args.source_dir,args.inventory,args.out)
    print(json.dumps({"source_row_count":manifest["source_row_count"],"training_ready":False}))


if __name__=="__main__": main()
