"""Rebuild six before/after source replays and a numerical audit, offline.

The same NTSB history is deliberately reused across weather scenarios. These
are sensitivity replays, not independent samples or a training dataset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .audit_reference import audit_reference, pressure_variability
from .io import simulate_to_directory
from .reference_episode import prepare_reference_episode

ROOT = Path(__file__).resolve().parent
EPISODES = tuple(f"{site}_{season}_2024" for site in ("red_sea_coast", "inland_desert")
                 for season in ("summer", "winter", "rain"))


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build(output_dir: str | Path, *, source_dir: str | Path = ROOT / "reference_data",
          channel_dir: str | Path = ROOT.parent / "outputs/ntsb_pressure_audit_v1/west_spill_1067220",
          start_local: str = "2025-09-13 15:00", seed: int = 42) -> dict:
    out, source_dir, channel_dir = Path(output_dir), Path(source_dir), Path(channel_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    comparisons = {}
    for episode in EPISODES:
        runs = {}
        for label, mode in (("periodic", "periodic_benchmark_surrogate"),
                            ("nonperiodic", "ntsb_relative_upstream")):
            prepared, simulated = out / episode / label / "prepared", out / episode / label / "simulated"
            reference = prepare_reference_episode(
                source_dir, episode, ROOT / "examples/reference_template_config.json", prepared,
                ROOT / "examples/reference_gas_assumptions.json", pressure_mode=mode,
                ntsb_pressure_dir=channel_dir if label == "nonperiodic" else None,
                ntsb_start_local=start_local if label == "nonperiodic" else None,
            )
            simulate_to_directory(prepared / "config.json", prepared / "forcing.csv", simulated, seed)
            audit = audit_reference(prepared, simulated)
            (out / episode / label / "audit.json").write_text(
                json.dumps(audit, indent=2) + "\n", encoding="utf-8")
            runs[label] = {"prepared": str(prepared.relative_to(out)),
                           "simulated": str(simulated.relative_to(out)), "audit": audit,
                           "forcing_sha256": reference["output_sha256"]["forcing.csv"]}
        before = _rows(out / runs["periodic"]["prepared"] / "forcing.csv")
        after = _rows(out / runs["nonperiodic"]["prepared"] / "forcing.csv")
        for a, b in zip(before, after):
            if {k: v for k, v in a.items() if k != "pressure_pa"} != {
                k: v for k, v in b.items() if k != "pressure_pa"
            }:
                raise ValueError("before/after differs outside pressure forcing")
        old_stats, new_stats = (runs[label]["audit"]["pressure_variability"]
                                for label in ("periodic", "nonperiodic"))
        if old_stats["lag24_exact_match_fraction"] != 1 or new_stats["lag24_exact_match_fraction"] == 1:
            raise ValueError("expected periodic baseline and changed nonperiodic replay")
        comparisons[episode] = {"runs": runs, "all_nonpressure_forcing_identical": True}
    first = out / EPISODES[0] / "nonperiodic" / "prepared"
    reference = json.loads((first / "reference_manifest.json").read_text(encoding="utf-8"))
    source_hourly = _rows(first / "pressure_hourly_snapshot.csv")
    source_metrics = pressure_variability([float(row["source_native_hourly_median"]) for row in source_hourly])
    summary = {
        "schema_version": "1", "training_ready": False, "seed": seed,
        "source_statement": "NASA POWER archived weather + TRR154 benchmark flow + transferred NTSB pre-onset pressure ratios + simulated saddle readout",
        "pressure_profile": reference["pressure_profile"],
        "source_hourly_native_metrics": source_metrics,
        "weather_scenario_count": len(comparisons), "simulation_run_count": 2 * len(comparisons),
        "independent_pressure_source_window_count": 1,
        "axial_heat_exchange_exposure_length_m": 0,
        "comparisons": comparisons,
        "limits": [
            "Pre-onset is not certified fault-free; no event hour or post-event values are used.",
            "NTSB ratios drive the inlet; the resulting local pressure is not a measured NTSB or Saudi pressure.",
            "Weather 2024 and source-local pressure 2025 are paired by elapsed position, not UTC simultaneity.",
            "Flow remains the periodic TRR154 surrogate; pressure correction does not fix flow realism.",
            "The same pressure window is reused in all six weather scenarios; keep them together in any future split.",
            "No saddle calibration, defect diagnosis, performance estimate or training is performed.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_report(out, summary)
    files = {str(path.relative_to(out)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(out.rglob("*")) if path.is_file()}
    (out / "files_sha256.json").write_text(json.dumps(files, indent=2) + "\n", encoding="utf-8")
    return summary


def _write_report(out: Path, summary: dict) -> None:
    first = summary["comparisons"][EPISODES[0]]["runs"]
    a, b = (first[k]["audit"]["pressure_variability"] for k in ("periodic", "nonperiodic"))
    c = summary["source_hourly_native_metrics"]
    profile = summary["pressure_profile"]
    report = f"""# استئناف محاكي قائف: إزالة تكرار الضغط — 2 أكتوبر 2026

نُفذ مسار اختياري `ntsb_relative_upstream` ينقل نسب تغير الضغط من قناة NTSB West Spill إلى ضغط منبع الأنبوب المرجعي، ثم يحسب الضغط المحلي بمعادلة الجريان نفسها. بقي المسار الافتراضي القديم `periodic_benchmark_surrogate` متاحًا وموسومًا صراحة للمقارنة وإعادة إنتاج النتائج السابقة.

## ما أُنتج وما ثبت

- ست حلقات طقس: صيف/شتاء/مطر لكل من الإحداثيتين الساحلية والصحراوية؛ نسختان لكل حلقة = 12 تشغيلًا، مع 169 صفًا لكل تشغيل.
- جميع فحوص التدقيق في التشغيلات ناجحة: البصمات، محاذاة الوقت، القنوات المحدودة، فصل الوسوم، ونسب الضغط واستبعاد فترة الحادث.
- جميع مدخلات كل مقارنة متطابقة عدا الضغط؛ التدفق والطقس والحرارة ومعلمات السرج والبذرة متطابقة.
- لم تُعدّل المخرجات القديمة، ولم يُشغّل تدريب؛ `training_ready=false` في جميع النتائج.

| السلسلة، 168 ساعة | مدى التغير / وسيط السلسلة | وسيط التغير الساعي / الوسيط | المئين 95 للتغير الساعي / الوسيط | تطابق أزواج فرق 24 ساعة |
|---|---:|---:|---:|---:|
| الضغط المحلي الدوري القديم، Pa فرق ضغط | {a['range_over_own_median_pct']:.3f}% | {a['median_abs_hourly_delta_over_own_median_pct']:.3f}% | {a['p95_abs_hourly_delta_over_own_median_pct']:.3f}% | {100*a['lag24_exact_match_fraction']:.1f}% |
| الضغط المحلي الجديد، Pa فرق ضغط | {b['range_over_own_median_pct']:.3f}% | {b['median_abs_hourly_delta_over_own_median_pct']:.3f}% | {b['p95_abs_hourly_delta_over_own_median_pct']:.3f}% | {100*b['lag24_exact_match_fraction']:.1f}% |
| المصدر NTSB، وحدة أصلية غير مطبوعة | {c['range_over_own_median_pct']:.3f}% | {c['median_abs_hourly_delta_over_own_median_pct']:.3f}% | {c['p95_abs_hourly_delta_over_own_median_pct']:.3f}% | {100*c['lag24_exact_match_fraction']:.1f}% |

يُستبعد صف التهيئة من هذه المقاييس. التغير يُقارن نسبةً إلى وسيط كل سلسلة، والمئين 95 محسوب بالاستيفاء الخطي بين الرتب. اختلاف هذه الأرقام عن التدقيق القديم متوقع: هنا نافذة محددة متطابقة من 168 ساعة، دون صف التهيئة أو الساعات الجزئية على أطراف كامل الأرشيف.

## المصدر والتحويل

النافذة `[{profile['window_start_local_inclusive']}, {profile['window_end_local_exclusive']})` بساعة المصدر المحلية غير معلومة المنطقة الزمنية. تشمل {profile['selected_record_count']:,} قراءة أصلية، بلا ساعات فارغة؛ أكبر فجوة داخلية {profile['max_internal_sample_gap_minutes']:g} دقيقة. كل القيم من `2025-09-20 23:00` فصاعدًا ممنوعة من هذا الموصل، بما فيها هبوط الحادث `23:05–23:25`.

التحويل: `p_up_abs(t) = p_up_initial × median_native(hour) / median_native(first_hour)`. لا تُحوّل وحدة West Spill غير المكتوبة إلى Pa. النسبة المنقولة افتراض تجربة، حتى للقناة الأخرى ذات PSIG؛ ليست معايرة ضغط مطلق. يُحسب الضغط المحلي من هذا المنبع مع التدفق المرجعي، وتُرفض أي قيمة تتجاوز نطاق مصدر GasLib المرجعي أو تجعل الضغط المطلق غير صالح، بدل قصها. نطاق مصدر GasLib ليس مواصفة مثبتة لموضع السرج.

تقترن ساعات الضغط بطقس NASA POWER من عام وموقع مختلفين حسب ترتيبها الزمني النسبي. هذه تجربة إعادة تشغيل وسيناريوهات حساسية، وليست رصدًا متزامنًا لنفس الأنبوب. الوسيط الساعي لمجموعة قراءات غير منتظمة ليس متوسطًا موزونًا بالزمن؛ تسجل أعداد القراءات وفجواتها وصفحات المصدر في `pressure_hourly_snapshot.csv`. التجميع مصمم لإعادة تشغيل أرشيفية، وليس لاستنتاج إنذار سببي داخل الساعة.

## الحدود والعمل التالي

أزيل التكرار الحرفي من الضغط في المسار الجديد فقط؛ التدفق يبقى دوريًا ومعلن المصدر. حلقة NTSB السابقة للحادث ليست تشغيلًا سليمًا موثقًا ولا توزيعًا سعوديًا أو قاعدة تدريب نهائية. **مصدر ضغط مستقل واحد فقط** أُعيد استخدامه مع حلقات الطقس الست؛ لا تُحسب هذه ست عينات تشغيل مستقلة، وتبقى جميع نوافذ/قنوات الحادث ومشتقاتها في مجموعة تقسيم واحدة مستقبلًا.

التسليم الحالي يعالج العيب الذي توقف عنده العمل. بقي قبل مجموعة بحثية مكتملة: سجل أدلة ونطاقات المعلمات، ملفات أصل/موقع مناسبة، مصادر تشغيل مستقلة، سيناريوهات وضوابط صعبة وفحوص قبل التدخل والتوزيع والتقسيم. ما زالت معايرة السرج الفيزيائي ومدى الكشف خارج ما تثبته هذه الشيفرة.

## الملفات وإعادة التشغيل

- `summary.json`: نتائج المقارنة وحدودها وسجل مصدر الضغط.
- `files_sha256.json`: بصمات كل الملفات الأخرى.
- داخل كل حلقة: `periodic/prepared`, `periodic/simulated`, `nonperiodic/prepared`, `nonperiodic/simulated` وتقرير `audit.json` لكل فرع.
- أداة إعادة البناء في المشروع: `python -m qaif_saddle_sim.build_pressure_comparison --out <مجلد جديد>`.
"""
    (out / "REPORT_AR.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--sources", default=str(ROOT / "reference_data"))
    parser.add_argument("--ntsb-pressure-dir", default=str(ROOT.parent / "outputs/ntsb_pressure_audit_v1/west_spill_1067220"))
    parser.add_argument("--ntsb-start-local", default="2025-09-13 15:00")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    summary = build(args.out, source_dir=args.sources, channel_dir=args.ntsb_pressure_dir,
                    start_local=args.ntsb_start_local, seed=args.seed)
    print(json.dumps({"output_dir": args.out, "run_count": summary["simulation_run_count"],
                      "independent_pressure_windows": 1, "training_ready": False}))


if __name__ == "__main__":
    main()
