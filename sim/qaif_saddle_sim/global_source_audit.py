"""Merge source dependency graphs across saved studies before reusing their data."""
import argparse
import json
from pathlib import Path

from .study_audit import connected_groups


def reference_tokens(reference):
    source=reference["source_files"];tokens=[]
    tokens.append("asset:"+reference["gaslib_properties"]["pipe_id"])
    for key,prefix in (("gaslib_network","benchmark:"),("trr_boundary","flow:")):
        if key in source:tokens.append(prefix+source[key]["sha256"])
    weather=reference["weather_source_key"]
    tokens.append("weather:"+source[weather]["sha256"])
    pressure=reference.get("pressure_profile",{})
    if "source_group_id" in pressure:tokens.append("pressure:"+pressure["source_group_id"])
    return tokens


def audit_saved_studies(studies):
    records=[];inventory=[]
    for index,directory in enumerate(map(Path,studies)):
        summary=json.loads((directory/"summary.json").read_text(encoding="utf-8"))
        namespace=f"study_{index:03d}:";before=len(records)
        if "pairs" in summary:
            for row in summary["pairs"]+summary.get("sensitivity",[]):
                records.append({"record_id":namespace+row["record_id"],"source_tokens":row["source_tokens"]})
        elif "comparisons" in summary:
            for reference_path in sorted(directory.rglob("reference_manifest.json")):
                reference=json.loads(reference_path.read_text(encoding="utf-8"))
                records.append({"record_id":namespace+str(reference_path.relative_to(directory)),
                                "source_tokens":reference_tokens(reference)})
        else:raise ValueError("saved study has no supported source-record inventory")
        inventory.append({"study_path":str(directory.resolve()),"record_count":len(records)-before})
    groups=connected_groups(records)
    return {"schema_version":"1","studies":inventory,"source_component_count":len(groups),"groups":groups,
            "train_validation_test_created":False,"training_ready":False,
            "rule":"Always recompute the union if old and new artifacts are combined; local group IDs are not global identities."}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--study",action="append",required=True)
    parser.add_argument("--out",required=True);args=parser.parse_args();result=audit_saved_studies(args.study)
    Path(args.out).write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"combined_source_component_count":result["source_component_count"],"training_ready":False}))


if __name__=="__main__":main()
