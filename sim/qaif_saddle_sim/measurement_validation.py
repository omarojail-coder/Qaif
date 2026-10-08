"""Compare independently sourced traces under an explicit measurement contract."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from .evidence_registry import sha256
from .study_audit import rows

UNITS={"strain_hoop_microstrain":"microstrain","strain_axial_microstrain":"microstrain",
       "temperature_k":"K","wetness_index":"dimensionless_0_1"}


def compare_measurements(simulated_dir,measurement_csv,metadata_json):
    simulated_dir,measurement_csv,metadata_json=map(Path,(simulated_dir,measurement_csv,metadata_json))
    simulation=json.loads((simulated_dir/"manifest.json").read_text(encoding="utf-8"))
    for name,digest in simulation["output_files"].items():
        if sha256(simulated_dir/name)!=digest:
            raise ValueError("simulation output/snapshot hash mismatch")
    metadata=json.loads(metadata_json.read_text(encoding="utf-8"))
    if (metadata.get("schema_version")!="1" or metadata.get("declared_independent_measurements") is not True
            or metadata.get("source_kind") not in {"bench_measurement","field_measurement","published_measurement"}
            or not metadata.get("source_uri") or not metadata.get("measurement_protocol_uri")):
        raise ValueError("measurement source/protocol/independence declaration missing")
    if metadata.get("measurement_csv_sha256")!=sha256(measurement_csv):
        raise ValueError("measurement trace hash mismatch")
    if metadata.get("model_config_snapshot_sha256")!=sha256(simulated_dir/"config_snapshot.json"):
        raise ValueError("measurement comparison is not bound to the declared model configuration")
    if metadata.get("installation")!="aboveground" or metadata.get("time_alignment")!="same elapsed time; no interpolation":
        raise ValueError("measurement scope/clock alignment unsupported")
    unit_map=metadata.get("channel_units",{})
    if not unit_map or any(UNITS.get(k)!=unit for k,unit in unit_map.items()):
        raise ValueError("measurement channels/units differ from simulator contract")
    tolerances=metadata.get("comparison_tolerances",{})
    if set(tolerances)!=set(unit_map):raise ValueError("channel-specific comparison tolerances required")
    for channel,limits in tolerances.items():
        if set(limits)!={"rmse_max","abs_bias_max"}:raise ValueError("incomplete comparison limits")
        if any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in limits.values()):
            raise ValueError("comparison tolerances must be positive finite")
    with measurement_csv.open(encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if len(reader.fieldnames or [])!=len(unit_map)+1 or set(reader.fieldnames or [])!={"timestamp_s",*unit_map}:
            raise ValueError("measurement columns do not match declared channels")
        measured=list(reader)
    observed_rows=rows(simulated_dir/"observed.csv")
    observed={float(r["timestamp_s"]):r for r in observed_rows}
    if len(observed_rows)!=len(observed) or len(observed_rows)!=simulation["sample_count"]:
        raise ValueError("simulation sample count/timestamps invalid")
    differences={channel:[] for channel in unit_map};previous=-math.inf
    for row in measured:
        time=float(row["timestamp_s"])
        if not math.isfinite(time) or time<0 or time<=previous or time not in observed:
            raise ValueError("measurement time is nonfinite, duplicate, missing, or requires interpolation")
        previous=time
        obs=observed[time]
        for channel in unit_map:
            if row[channel]=="":continue
            value=float(row[channel])
            if not math.isfinite(value) or (channel=="wetness_index" and not 0<=value<=1):
                raise ValueError("invalid measured value")
            if obs["packet_valid"]=="True":
                differences[channel].append(float(obs[channel])-value)
    results={}
    for channel,delta in differences.items():
        if len(delta)<5:raise ValueError("fewer than five aligned valid samples for a measurement channel")
        bias=sum(delta)/len(delta);rmse=math.sqrt(sum(v*v for v in delta)/len(delta))
        limits=tolerances[channel]
        results[channel]={"sample_count":len(delta),"unit":unit_map[channel],"bias":bias,"rmse":rmse,
                          "max_abs_error":max(abs(v) for v in delta),"declared_limits":limits,
                          "within_declared_limits":rmse<=limits["rmse_max"] and abs(bias)<=limits["abs_bias_max"]}
    return {"schema_version":"1","measurement_csv_sha256":sha256(measurement_csv),
            "measurement_metadata_sha256":sha256(metadata_json),"source_uri":metadata["source_uri"],
            "measurement_protocol_uri":metadata["measurement_protocol_uri"],"channels":results,
            "comparison_within_declared_limits":all(r["within_declared_limits"] for r in results.values()),
            "provenance_status":"declared by source metadata; requires independent review",
            "qaif_calibrated":False,"field_validated":False,"training_ready":False,
            "limits":["Trace comparison alone does not prove provenance or validate a saddle transfer model.",
                      "Tolerances come from the declared protocol; they are not a fitted acceptance threshold.",
                      "No gain/lag parameters are silently fitted and no readiness flag is enabled."]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("simulated","measurements","metadata","out"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args();report=compare_measurements(args.simulated,args.measurements,args.metadata)
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"comparison_within_declared_limits":report["comparison_within_declared_limits"],"qaif_calibrated":False}))


if __name__=="__main__":main()
