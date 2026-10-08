"""Conditional feature audits and disposable shortcut diagnostics, not task training."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from .evidence_registry import sha256
from .study_audit import CHANNELS, connected_groups, rows, validate_split_assignment


def features(observed, context, end_s=None):
    """Timeline/administrative IDs excluded; finite common signal summaries only."""
    selected=[r for r in observed if end_s is None or float(r["timestamp_s"])<=end_s]
    environment=[r for r in context if end_s is None or float(r["timestamp_s"])<=end_s]
    if not selected or len(selected)!=len(environment):
        raise ValueError("empty/misaligned feature window")
    result=[]
    for key in CHANNELS:
        values=[float(r[key]) for r in selected if r["packet_valid"]=="True"]
        if not values:
            raise ValueError("no valid pre-event readings")
        mean=sum(values)/len(values)
        result.extend((mean,math.sqrt(sum((v-mean)**2 for v in values)/len(values)),min(values),max(values)))
    result.append(sum(r["packet_valid"]=="False" for r in selected)/len(selected))
    for key in environment[0]:
        if key=="timestamp_s": continue
        values=[float(r[key]) for r in environment]
        result.extend((sum(values)/len(values),min(values),max(values)))
    if any(not math.isfinite(v) for v in result):
        raise ValueError("nonfinite audit feature")
    return result


def _balanced_accuracy(labels,predictions):
    classes=sorted(set(labels))
    return sum(sum(a==b for a,b in zip(labels,predictions) if a==cls)/labels.count(cls) for cls in classes)/len(classes)


def centroid_holdout(examples):
    """Leave entire source components out; scaling/centroids use training only."""
    groups=sorted({row["group"] for row in examples})
    if len(groups)<2:
        return {"status":"unavailable","reason":"fewer than two source components"}
    all_labels=[];predictions=[];folds=[]
    for group in groups:
        train=[r for r in examples if r["group"]!=group]
        test=[r for r in examples if r["group"]==group]
        if any({r["label"] for r in dataset}!={0,1} for dataset in (train,test)):
            return {"status":"unavailable","reason":"a component fold lacks both diagnostic labels"}
        n=len(train);dimensions=len(train[0]["x"])
        mean=[sum(r["x"][j] for r in train)/n for j in range(dimensions)]
        scale=[math.sqrt(sum((r["x"][j]-mean[j])**2 for r in train)/n) or 1 for j in range(dimensions)]
        centers=[]
        for label in (0,1):
            subset=[r for r in train if r["label"]==label]
            centers.append([sum((r["x"][j]-mean[j])/scale[j] for r in subset)/len(subset) for j in range(dimensions)])
        labels=[];pred=[]
        for row in test:
            distances=[sum(((row["x"][j]-mean[j])/scale[j]-center[j])**2 for j in range(dimensions)) for center in centers]
            # Equal distances choose a fixed class, not a branch/source ID.
            choice=int(distances[1]<distances[0] and not math.isclose(distances[0],distances[1],rel_tol=1e-12,abs_tol=1e-12))
            labels.append(row["label"]);pred.append(choice)
        folds.append({"heldout_component":group,"test_example_count":len(test),"balanced_accuracy":_balanced_accuracy(labels,pred)})
        all_labels+=labels;predictions+=pred
    return {"status":"computed","classifier":"standardized nearest class centroid",
            "balanced_accuracy":_balanced_accuracy(all_labels,predictions),"folds":folds,
            "source_component_count":len(groups),"model_weights_saved":False,
            "scope":"disposable generator shortcut diagnostic; no alarm model is trained"}


def shortcut_diagnostic(examples, permutations=99, seed=84):
    actual=centroid_holdout(examples)
    if actual["status"]!="computed": return actual
    if not isinstance(permutations,int) or isinstance(permutations,bool) or permutations<1:
        raise ValueError("positive permutation count required")
    paired=defaultdict(list)
    for row in examples: paired[row["pair"]].append(row)
    if any(len(v)!=2 or {r["label"] for r in v}!={0,1} or len({r["group"] for r in v})!=1 for v in paired.values()):
        raise ValueError("diagnostic needs matched binary pairs inside one source component")
    rng=random.Random(seed);scores=[]
    for _ in range(permutations):
        permuted=[]
        for pair in paired.values():
            flip=rng.randrange(2)
            permuted.extend({**row,"label":row["label"]^flip} for row in pair)
        scores.append(centroid_holdout(permuted)["balanced_accuracy"])
    return {**actual,"permutation_count":permutations,"permutation_method":"swap labels within matched pairs, preserving source/weather/schedule/sensor strata",
            "null_mean_balanced_accuracy":sum(scores)/len(scores),"null_max_balanced_accuracy":max(scores),
            "one_sided_permutation_p":(1+sum(score>=actual["balanced_accuracy"]-1e-12 for score in scores))/(1+len(scores))}


def plan_source_split(records):
    groups=connected_groups(records)
    if len(groups)<3:
        return {"status":"unavailable","source_component_count":len(groups),"groups":groups,
                "assignments":{r["record_id"]:"research_inspection_only" for r in records},
                "train_validation_test_created":False,
                "reason":"at least three disjoint source components needed for three separate sets"}
    partitions=("train","validation","test")
    assignments={identifier:partitions[i%3] for i,group in enumerate(groups) for identifier in group["record_ids"]}
    validate_split_assignment(groups,assignments)
    return {"status":"proposed_only","source_component_count":len(groups),"groups":groups,
            "assignments":assignments,"train_validation_test_created":False,
            "reason":"a proposed source partition does not satisfy calibration or coverage gates"}


def audit_study(directory,records,permutations=99):
    directory=Path(directory)
    plan=plan_source_split(records)
    group_by_id={identifier:group["group_id"] for group in plan["groups"] for identifier in group["record_ids"]}
    end=min(r["physical_start_s"] for r in records)
    examples=[];context_examples=[];fingerprints=defaultdict(list);conditional=[]
    for record in records:
        pair=directory/record["pair_dir"]
        observed=[rows(pair/branch/"observed.csv") for branch in ("control","intervention")]
        context=[rows(pair/branch/"context.csv") for branch in ("control","intervention")]
        prefix=[[r for r in dataset if float(r["timestamp_s"])<=end] for dataset in observed]
        if prefix[0]!=prefix[1] or context[0]!=context[1]:
            raise ValueError("pre-event/context branch shortcut detected")
        conditional.append({"record_id":record["record_id"],"stratum":[record["base_id"],record["sensor_profile_id"],record["schedule_id"]],
                            "pre_event_max_abs_feature_delta":0,"context_max_abs_feature_delta":0})
        for label,branch in enumerate(("control","intervention")):
            group=group_by_id[record["record_id"]]
            examples.append({"pair":record["record_id"],"group":group,"label":label,
                             "x":features(observed[label],context[label],end)})
            ctx=context[label]
            vector=[]
            for key in ctx[0]:
                if key=="timestamp_s": continue
                values=[float(r[key]) for r in ctx]
                vector.extend((sum(values)/len(values),min(values),max(values)))
            context_examples.append({"pair":record["record_id"],"group":group,"label":label,"x":vector})
            fingerprints[sha256(pair/branch/"observed.csv")].append({"record_id":record["record_id"],"branch":branch,"group":group})
    duplicates=[v for v in fingerprints.values() if len(v)>1]
    if any(len({r["group"] for r in members})>1 for members in duplicates):
        raise ValueError("identical observed series cross source components")
    return {"schema_version":"1","pre_event_window_end_s":end,"conditional_distributions":conditional,
            "pre_event_diagnostic":shortcut_diagnostic(examples,permutations),
            "signal_removed_context_only_diagnostic":shortcut_diagnostic(context_examples,permutations),
            "exact_observed_duplicate_groups":duplicates,"duplicates_cross_component":False,
            "source_split_plan":plan,"diagnostic_example_count":len(examples),
            "signal_feature_counts_as_independent_samples":False,
            "administrative_identifiers_used_as_features":False,
            "limits":["Two source components are a limited diagnostic, not three-way model evaluation.",
                       "Exact paired distribution identity does not establish broader field distribution coverage.",
                       "No event-signal classifier, threshold calibration, or predictive ablation experiment is performed.",
                       "No alarm model weights are stored; source and calibration gates remain separate."],
            "training_ready":False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--study",required=True)
    parser.add_argument("--out",required=True);args=parser.parse_args()
    root=Path(args.study);summary=json.loads((root/"summary.json").read_text(encoding="utf-8"))
    audit=audit_study(root,summary["pairs"])
    Path(args.out).write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"source_component_count":audit["source_split_plan"]["source_component_count"],"training_ready":False}))


if __name__=="__main__": main()
