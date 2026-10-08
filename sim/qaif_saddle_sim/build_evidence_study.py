"""Offline parameter sensitivity and matched local-mechanism research study.

No training, classifier fitting, field-ready label or independent split is made.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .config import Config
from .evidence_registry import (load_registry, validate_profiles, validate_nominals,
                                set_parameter, export_registry_csv, sha256)
from .experiment import export_pair, _write_steps
from .io import read_forcing, simulate_to_directory
from .reference_episode import prepare_reference_episode, _weather_rows
from .replay_grid import hold_refine
from .timeline import build_timeline
from .study_audit import (audit_pair, audit_run, rows, compare_channels,
                         connected_groups, validate_split_assignment, CHANNELS)

ROOT = Path(__file__).resolve().parent
SENSITIVITY_AXES = (
    "config.wall_thickness_m", "config.young_modulus_pa", "config.coating.conductivity_w_mk",
    "config.solar_absorptivity", "config.axial_restraint_fraction", "config.active_length_m",
    "config.thermal_sector_angle_rad", "config.strain_hoop.gain", "config.strain_hoop.lag_s",
    "config.temperature.lag_s", "config.wetness.lag_s", "config.wet_ingress_rate_per_s",
    "config.wet_drying_rate_per_s", "gas.effective_axial_exposure_length_m",
)


def _json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n",encoding="utf-8")


def _tokens(reference: dict) -> list[str]:
    return ["asset:"+reference["gaslib_properties"]["pipe_id"],
            "pressure:"+reference["pressure_profile"]["source_group_id"],
            "weather:"+reference["source_files"][reference["weather_source_key"]]["sha256"]]


def _probe(steps, period):
    # Explicit separate local-load and wet-path probes, not an incident trace.
    result=[]
    for step in steps:
        overrides={}
        if 12*3600 < step.timestamp_s <= 18*3600:
            overrides={"bending_moment_nm":2000,"event_type":"mechanical_change"}
        if 18*3600 < step.timestamp_s <= 48*3600:
            overrides={"wet_path_open":True,"event_type":"interface_wetting" if step.wet_drive>0 else "normal_environment"}
        result.append(replace(step,**overrides))
    return result


def _timeline(config, site_id, family, mechanism, start, end, change, period, final, case=False):
    # Existing timeline API selects sample timestamps. Shift phase bounds by
    # one period so first affected end sample applies over (start,start+period].
    spec={"schema_version":"1","asset_id":config.asset_id,"site_id":site_id,
          "base_episode_id":config.source_episode_id,"scenario_family_id":family,
          "mechanism_id":mechanism,"evidence_level":"declared_research_grid",
          "unknown_assumptions":["Amplitude/duration/onset are constructed, not measured case values.",
                                 "No calibrated saddle transfer function or field defect label."],
          "phases":[{"phase_id":"local_intervention","event_type":mechanism,
                     "start_s":start+period,"end_s":end+period,
                     "changes":{key:{"mode":"hold","value":value} for key,value in change.items()}},
                    {"phase_id":"recovery_observation","event_type":"normal_environment",
                     "start_s":end+period,"end_s":final+period,"changes":{}}]}
    if case: spec["inspired_by_case_id"]="QC-02"
    return spec


def build(output_dir: str | Path, *, sources: str | Path = ROOT/"reference_data",
          channel_dir: str | Path = ROOT.parent/"outputs/ntsb_pressure_audit_v1/west_spill_1067220",
          registry_path: str | Path = ROOT/"evidence/parameter_registry.json",
          profiles_path: str | Path = ROOT/"evidence/profiles.json",
          period_s: int = 600, seed: int = 42) -> dict:
    out,sources=Path(output_dir),Path(sources)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    if period_s not in {300,600,1800}:
        raise ValueError("study sample period must be a declared 300/600/1800 s grid point")
    template=json.loads((ROOT/"examples/reference_template_config.json").read_text(encoding="utf-8"))
    assumptions=json.loads((ROOT/"examples/reference_gas_assumptions.json").read_text(encoding="utf-8"))
    registry=load_registry(registry_path,template,assumptions)
    profiles=validate_profiles(profiles_path,sources)
    budget=profiles["asset"]["stress_budget_pa"]
    out.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(registry_path,out/"parameter_registry_snapshot.json")
    shutil.copyfile(profiles_path,out/"profiles_snapshot.json")
    export_registry_csv(registry,out/"parameter_evidence.csv")
    prepared_references={}
    pairs=[]
    records=[]
    case_comparisons=[]
    inventory=json.loads((sources/"source_manifest.json").read_text(encoding="utf-8"))["entries"]
    for site in profiles["sites"]:
        for season in ("rain","summer"):
            episode=next(key for key in site["episode_source_keys"] if f"_{season}_" in key)
            weather,_=_weather_rows(sources/inventory[episode]["path"])
            # Same 72-hour relative window, with 12+ hours of pre-event history.
            weather_start=weather[48]["utc_hour"]
            prepared=out/"bases"/episode
            reference=prepare_reference_episode(
                sources,episode,ROOT/"examples/reference_template_config.json",prepared,
                ROOT/"examples/reference_gas_assumptions.json",window_start_utc=weather_start,window_hours=72,
                pressure_mode="ntsb_relative_upstream",ntsb_pressure_dir=channel_dir,
                ntsb_start_local="2025-09-13 15:00")
            prepared_references[episode]=reference
            config=Config.from_json(prepared/"config.json")
            validate_nominals(registry,json.loads((prepared/"config.json").read_text()),assumptions)
            refined=hold_refine(read_forcing(prepared/"forcing.csv"),period_s)
            if config.asset_id != profiles["asset"]["asset_id"]:
                raise ValueError("prepared asset does not match asset profile")
            starts=[18*3600,24*3600]
            if season=="rain":
                wet_times=[s.timestamp_s-period_s for s in refined if s.timestamp_s>=12*3600 and s.wet_drive>0]
                if not wet_times:
                    raise ValueError("chosen rain window has no supported wetting opportunity")
                first=wet_times[0]
                later=next(time for time in wet_times if time>=first+6*3600)
                starts=[first,later]
            # Every mechanism family shares both schedule slots within the
            # same weather window. Onset/duration are not class-specific.
            plans=[]
            for slot,start in enumerate(starts):
                suffix="early" if slot==0 else "late"
                duration=(6 if slot==0 else 12)*3600
                multiplier=.7 if slot==0 else .4
                plans += [("local_bending_"+suffix,"mechanical_change",start,duration,
                           {"bending_moment_nm":2000 if slot==0 else 8000}),
                          ("coupling_drop_"+suffix,"sensor_fault",start,duration,
                           {"hoop_coupling_multiplier":multiplier,"axial_coupling_multiplier":multiplier}),
                          ("forced_packet_loss_"+suffix,"sensor_fault",start,duration,{"force_missing":True}),
                          ("wetness_flatline_"+suffix,"sensor_fault",start,duration,{"wetness_flatline":True})]
                if season=="rain":
                    plans.append(("wet_path_"+suffix,"interface_wetting",start,duration,{"wet_path_open":True}))
            if season=="rain":
                plans.append(("wet_path_early_case_QC02","interface_wetting",starts[0],6*3600,{"wet_path_open":True}))
            site_pairs={}
            for family,mechanism,start,duration,change in plans:
                end=start+duration
                spec=_timeline(config,site["site_id"],family,mechanism,start,end,change,period_s,
                               refined[-1].timestamp_s,case=family.endswith("case_QC02"))
                event_steps,labels,counts,case=build_timeline(config,refined,spec)
                pair_dir=out/"scenarios"/episode/family
                manifest=export_pair(config,refined,event_steps,pair_dir,seed,spec,mechanism,
                    sum(counts.values()),case,split_group="source_component_pending",
                    spec_filename="timeline_spec.json",reference_provenance=reference,
                    extra_manifest={"site_id":site["site_id"],"mechanism_id":mechanism,
                        "scenario_family_id":family,"physical_window_start_s":start,
                        "physical_window_end_s":end,"source_sample_period_s":3600,
                        "simulation_sample_period_s":period_s,
                        "reference_provenance_scope":"parent hourly forcing before offline hold refinement",
                        "reconstruction":"row k>0 held over preceding interval; no new measured time detail"})
                labels_path=pair_dir/"inputs/timeline_samples.csv"
                with labels_path.open("w",encoding="utf-8",newline="") as handle:
                    writer=csv.DictWriter(handle,fieldnames=list(labels[0]))
                    writer.writeheader(); writer.writerows(labels)
                manifest["timeline_samples_sha256"]=sha256(labels_path)
                _json(pair_dir/"paired_manifest.json",manifest)
                audit=audit_pair(pair_dir,start,period_s,budget,mechanism)
                _json(pair_dir/"audit.json",audit)
                item={"record_id":episode+":"+family,"pair_dir":str(pair_dir.relative_to(out)),
                      "site_id":site["site_id"],"weather_episode":episode,"family":family,
                      "mechanism":mechanism,"physical_start_s":start,"duration_s":duration,
                      "source_tokens":_tokens(reference),"audit":audit}
                records.append(item); pairs.append(item); site_pairs[family]=pair_dir
            if season=="rain":
                generic,inspired=(site_pairs[key] for key in ("wet_path_early","wet_path_early_case_QC02"))
                identical=all((generic/branch/name).read_bytes()==(inspired/branch/name).read_bytes()
                              for branch in ("control","intervention") for name in ("observed.csv","context.csv"))
                if not identical:
                    raise ValueError("case provenance changed the observed/context signal")
                case_comparisons.append({"episode":episode,"generic_case_outputs_identical":True,
                                         "intentional_duplicate_for_source_audit":True})

    # One-factor-at-a-time study on one rain replay, with all other parameters
    # fixed. Initial conditions, pressure, weather and random draws are shared.
    entries={entry["parameter_id"]:entry for entry in registry["parameters"]}
    nominal_episode="red_sea_coast_rain_2024"
    nominal_weather_start=prepared_references[nominal_episode]["weather_first_utc_hour"]
    variants=[("nominal",None,None)]
    for identifier in SENSITIVITY_AXES:
        entry=entries[identifier]
        for value in entry["sweep_values"]:
            if value != entry["nominal"]:
                variants.append((f"v{len(variants):03d}",identifier,value))
    sensitivities=[]
    nominal_observed=None
    for variant_id,identifier,value in variants:
        variant=out/"sensitivity"/variant_id
        variant_template=json.loads(json.dumps(template)); variant_gas=dict(assumptions)
        if identifier:
            entry=entries[identifier]
            set_parameter(variant_template if entry["scope"]=="config" else variant_gas,entry["path"],value)
        _json(variant/"inputs/template.json",variant_template)
        _json(variant/"inputs/gas_assumptions.json",variant_gas)
        prepared=variant/"prepared"
        reference=prepare_reference_episode(sources,nominal_episode,variant/"inputs/template.json",prepared,
            variant/"inputs/gas_assumptions.json",window_start_utc=nominal_weather_start,window_hours=72,
            pressure_mode="ntsb_relative_upstream",ntsb_pressure_dir=channel_dir,ntsb_start_local="2025-09-13 15:00")
        refined=hold_refine(read_forcing(prepared/"forcing.csv"),period_s)
        probe=_probe(refined,period_s)
        _write_steps(variant/"inputs/probe_forcing.csv",probe)
        shutil.copyfile(prepared/"config.json",variant/"inputs/config.json")
        simulate_to_directory(variant/"inputs/config.json",variant/"inputs/probe_forcing.csv",variant/"simulated",seed)
        audit=audit_run(variant/"simulated",period_s,budget)
        observed=rows(variant/"simulated/observed.csv")
        if nominal_observed is None: nominal_observed=observed
        metrics=compare_channels(nominal_observed,observed)
        record={"record_id":"sensitivity:"+variant_id,"variant_id":variant_id,
                "parameter_id":identifier,"value":value,"parameter_unit":entries[identifier]["unit"] if identifier else None,
                "output_dir":str(variant.relative_to(out)),"source_tokens":_tokens(reference),
                "metrics":metrics,"audit":audit,
                "parent_reference_manifest_sha256":sha256(prepared/"reference_manifest.json")}
        _json(variant/"audit.json",record); sensitivities.append(record); records.append(record)

    groups=connected_groups(records)
    assignments={record["record_id"]:"research_inspection_only" for record in records}
    validate_split_assignment(groups,assignments)
    for group in groups:
        for record in records:
            if record["record_id"] in group["record_ids"]:
                record["source_group_id"]=group["group_id"]
                if "pair_dir" in record:
                    path=out/record["pair_dir"]/"paired_manifest.json"
                    paired=json.loads(path.read_text(encoding="utf-8"))
                    paired["split_group"]=group["group_id"]
                    paired["source_tokens"]=record["source_tokens"]
                    _json(path,paired)
    _json(out/"source_groups.json",{"groups":groups,"assignments":assignments,
           "train_validation_test_created":False,"independent_split_feasible":len(groups)>=3,
           "reason":"Shared benchmark asset and NTSB window connect the entire current study; never split rows/branches."})
    # Identical controls and the intentional generic/case duplicate must be
    # visible. They are not extra independent examples or signal validation.
    duplicate_map={}
    for item in pairs:
        for branch in ("control","intervention"):
            digest=sha256(out/item["pair_dir"]/branch/"observed.csv")
            duplicate_map.setdefault(digest,[]).append(item["record_id"]+":"+branch)
    duplicates=[members for members in duplicate_map.values() if len(members)>1]
    coverage=dict(Counter((item["weather_episode"]+":"+item["mechanism"]) for item in pairs))
    schedule_audit={}
    for episode in prepared_references:
        schedules={}
        for item in pairs:
            if item["weather_episode"]==episode and not item["family"].endswith("case_QC02"):
                schedules.setdefault(item["mechanism"],set()).add((item["physical_start_s"],item["duration_s"]))
        if any(values!=next(iter(schedules.values())) for values in schedules.values()):
            raise ValueError("mechanism schedules differ within weather stratum")
        schedule_audit[episode]={mechanism:sorted(values) for mechanism,values in schedules.items()}
    summary={"schema_version":"1","created_on":"2026-10-02","training_ready":False,
             "parameter_entry_count":len(registry["parameters"]),
             "numeric_config_gas_coverage_count":sum(entry["scope"] != "scenario" for entry in registry["parameters"]),
             "site_profile_count":len(profiles["sites"]),"weather_window_count":len(prepared_references),
             "source_period_s":3600,"simulation_period_s":period_s,"window_hours":72,"seed":seed,
             "scenario_pair_count":len(pairs),"sensitivity_axis_count":len(SENSITIVITY_AXES),
             "sensitivity_run_count":len(sensitivities),"independent_pressure_window_count":1,
             "source_component_count":len(groups),"split_created":False,
             "scenario_coverage":coverage,"case_vs_generic_comparisons":case_comparisons,
             "matched_onset_duration_by_weather":schedule_audit,
             "exact_observed_duplicate_groups":duplicates,"pairs":pairs,"sensitivity":sensitivities,
             "checks_passed":["registry_coverage_and_grid_semantics","site_geometry_source_hashes",
                "scenario_pre_intervention_identity","scenario_context_identity","sensor_fault_physics_identity",
                "wetting_requires_water_and_open_path","mechanical_response_and_stress_budget",
                "output_hashes_units_and_grid","case_provenance_no_signal_fingerprint",
                "transitive_source_groups_and_explicit_duplicates"],
             "limits":["No saddle calibration or field defect labels; grids are assumptions, not confidence intervals.",
                       f"{period_s}-second replay holds hourly inputs; it adds no measured source resolution.",
                       "Noise AR coefficients and packet-loss probabilities are per simulation sample; no continuous-time calibration is claimed.",
                       "No source-independent train/validation/test possible from this one connected component.",
                       "No distributional shortcut classifier, training or probability calibration performed.",
                       "Normal-operation pressure variability is a constructed multi-source replay, not certified healthy SCADA.",
                       "One-factor sensitivity is conditional on the selected grid/probe and is not a global importance estimate."]}
    _json(out/"summary.json",summary)
    _write_report(out,summary,registry)
    _json(out/"files_sha256.json",{str(p.relative_to(out)):sha256(p) for p in sorted(out.rglob("*")) if p.is_file()})
    return summary


def _write_report(out,summary,registry):
    lines=["# قائف: دليل المعلمات ومصفوفة تجارب محلية — 2 أكتوبر 2026", "",
        f"أُنشئ سجل {summary['parameter_entry_count']} معلمة، منها {summary['numeric_config_gas_coverage_count']} تغطي جميع الحقول العددية الفعلية لإعدادات المحاكي والغاز، بما فيها القيم الافتراضية المضمرة. رُبط بأصل معياري فوق الأرض وملفَي موقع شبكيين. القيم تخص مجال المحاكاة؛ لا توجد معايرة سرج أو درجة فولاذ/طلاء/لاصق مثبتة.","",
        "## الدليل ونطاقات المسح", "",
        "القطر 508 مم وحرارة الغاز المرجعية من GasLib. المراجع العامة للفولاذ تعطي نقاط مقارنة لمرونة وتمدد وخواص حرارية؛ لا تثبت المادة الخاصة بالأنبوب. أبقينا القيم الاسمية السابقة وحددنا نقاط مسح معلنة، لا نطاقات قياس أو توزيعات احتمالية. حدود الإجهاد 200 MPa حراسة بحثية مفترضة وليست مقاومة خضوع أو حد تصميم معتمد.","",
        "المراجع الأصلية التي تمت مراجعتها: [SCI P185، المذكرة 3.01، صفحة 3](https://www.steelconstruction.info/images/8/86/GN_3-01.pdf)، و[جدول خواص المواد المستضاف لدى NIST، صفحة الفولاذ](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=101567). سجل `parameter_registry_snapshot.json` يوضح ما يسنده كل مصدر وما لا يسنده. بقي `parameter_evidence_template.csv` القديم قالبًا تاريخيًا؛ السجل الفعلي هنا وداخل `qaif_saddle_sim/evidence/`.","",
        "## التشغيل والفحوص", "",
        f"بُنيت {summary['scenario_pair_count']} تجربة مزدوجة ({2*summary['scenario_pair_count']} تشغيلًا) فوق أربع نوافذ طقس من 72 ساعة: مطر وصيف لكل موقع. كل زوج يثبت الضغط والطقس والهندسة والبذرة ويغير آلية محلية فقط. أُجري مسح أحادي العامل على {summary['sensitivity_axis_count']} محورًا، بإجمالي {summary['sensitivity_run_count']} تشغيلًا تشمل الاسمي.","",
        "الحالات: عزم انحناء محلي، فتح مسار ماء في وقت هطول فعلي، انخفاض اقتران القراءة، فقد حزم، وتسطح حساس البلل. الفرع الضابط يحتوي تغير الضغط والجو والمطر نفسه مع واجهة مغلقة؛ المطر وحده لا يصبح عطل بلل. لا توجد وسوم شق/تسرب/عمق عيب.","",
        "اجتازت الأزواج تطابق ما قبل التدخل والسياق، وفصل البيانات الإدارية عن القنوات المرصودة، وحدود البلل والضغط والإجهاد، وثبات الحالة الفيزيائية في أعطال الحساس. أعيدت مقارنة الحالة العامة وQC-02 بالقيم نفسها: كانت القنوات المرصودة والسياق متطابقة بالبايت؛ بطاقة الحادث مصدر إلهام فقط.","",
        f"فترة المحاكاة {summary['simulation_period_s']} ثانية مع تثبيت مدخل كل ساعة على فترتها السابقة. الضغط والطقس ما زالا ساعيين. حدود مراحل timeline حُولت إلى صف نهاية الفترة التالي حتى يبدأ المؤثر عند بداية الفترة الفيزيائية المعلنة؛ لا تبدأ الآلية مبكرًا بعينة. التجميع أرشيفي وليس إثبات إنذار سببي داخل الساعة.","",
        "معامل ترابط الضجيج واحتمال فقد الحزمة معرفان لكل عينة محاكاة. تغيير فترة العينة يغير معناهما الزمني؛ لم تُعاير عملية ضجيج أو اتصال مستمرة الزمن. أُصلح استهلاك العدد العشوائي في فقد الحزم القسري حتى تعود القراءات بعد انتهائه إلى تسلسل الفرع الضابط نفسه. القراءات والسياق والحالة الفيزيائية في تشغيل مرجعي بلا فقد قسري بقيت متطابقة بالبايت مع الإصدار السابق.","",
        "## حساسية القنوات", "",
        "الجدول يعرض أكبر فرق مرصود عن الاسمي لكل محور عبر نقاط مسحه، بوحدة القناة. النتائج مشروطة بهذه النوافذ ونطاقات المسح والمحفزات؛ ليست ترتيب أهمية ميدانيًا ولا حد كشف.","",
        "| المعلمة | المحيطي µε | المحوري µε | الحرارة K | البلل [0,1] |", "|---|---:|---:|---:|---:|"]
    for axis in SENSITIVITY_AXES:
        items=[x for x in summary['sensitivity'] if x['parameter_id']==axis]
        maxima=[max(item['metrics'][key]['max_abs_delta'] for item in items) for key in CHANNELS]
        lines.append(f"| `{axis}` | "+" | ".join(f"{v:.5g}" for v in maxima)+" |")
    lines += ["", "`active_length_m` و`thermal_sector_angle_rad` يمثلان حجم القطاع الحراري، لا مدى كشف. في هذا النموذج تتغير المساحة والسعة والمقاومات مع الأبعاد نفسها، وقد تبقى الحرارة ثابتة تقريبًا؛ هذا حد بنيوي للنموذج، وليس دليلًا على عدم أهمية حجم السرج الحقيقي.","",
        "## استقلال المجموعة وحدود الجاهزية", "",
        f"مراجعة المصادر وجدت **{summary['source_component_count']} مكوّنًا مترابطًا فقط**: جميع التجارب تعتمد الأصل المعياري ونافذة NTSB نفسيهما، حتى عندما يختلف الطقس أو المعلمة أو البذرة أو نوع التدخل. `source_groups.json` يجمعها قبل أي تقسيم. لم ننشئ train/validation/test؛ تقسيم الصفوف أو الفروع سيعطي تقييمًا متسربًا.","",
        "النسخ الضابطة المتطابقة والتكرار المقصود بين العام وQC-02 ظاهرة في التقرير الآلي ولا تُحسب كأدلة مستقلة. الآلية المبتلة اختُبرت داخل شريحة مطر مناسبة، ولم تُختلق حالات بلل إيجابية في حلقات الصيف الجافة. ما زالت فحوص التوزيع الإحصائي ومصنف الاختصارات بحاجة إلى مجموعة أوسع ذات مصادر مستقلة، والتدريب مؤجل.","",
        "**الحالة:** مصفوفة تجارب بحثية قابلة لإعادة التشغيل ومراجعة اتساق، مع `training_ready=false` في كل النتائج. لا إثبات أداء ميداني، ولا احتمال فشل أو معدل أعطال سعودي. المرحلة التالية تحتاج أصلًا/مصادر تشغيل مستقلة وقياسات تحقق لمعلمات السرج؛ تكثير النوافذ والبذور وحده لا يحل نقص الاستقلال.","",
        "## الملفات", "",
        "- `parameter_registry_snapshot.json` و`parameter_evidence.csv`: قيم ووحدات ومصادر وحدود النقل.",
        "- `profiles_snapshot.json`: الأصل والموقعان والمعلومات المجهولة.",
        "- `bases/`: مدخلات ساعية موثقة غير دورية الضغط.",
        "- `scenarios/`: أزواج وضوابط ومراحل وقراءات وتقارير تدقيق.",
        "- `sensitivity/`: المسوح الأحادية والقيم الاسمية ومقاييس الفرق.",
        "- `summary.json`, `source_groups.json`, `files_sha256.json`: الجرد والاستقلال والبصمات.","",
        "إعادة البناء من المشروع: `python -m qaif_saddle_sim.build_evidence_study --out <مجلد جديد>`."]
    (out/"REPORT_AR.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    parser.add_argument("--sources",default=str(ROOT/"reference_data"))
    parser.add_argument("--ntsb-pressure-dir",default=str(ROOT.parent/"outputs/ntsb_pressure_audit_v1/west_spill_1067220"))
    parser.add_argument("--period-s",type=int,default=600)
    parser.add_argument("--seed",type=int,default=42)
    args=parser.parse_args()
    summary=build(args.out,sources=args.sources,channel_dir=args.ntsb_pressure_dir,period_s=args.period_s,seed=args.seed)
    print(json.dumps({key:summary[key] for key in ("scenario_pair_count","sensitivity_run_count","source_component_count","training_ready")}))


if __name__=="__main__": main()
