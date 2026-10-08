"""Declared research rules, not a trained or field calibrated model.

Replay reference is the matched control run. Labels, latent and forcing files
are never read. Live uploads without a reference only receive quality checks.
"""
import csv
import math
from pathlib import Path

CASES = {'early_bending':'تغير ميكانيكي', 'early_wet_path':'مسار بلل',
 'early_coupling':'تغير اقتران السرج','early_packet_gap':'انقطاع الحزم',
 'early_temperature_flatline':'ثبات حساس الحرارة','control':'تشغيل مرجعي'}
LIMITS = {'strain_axial_microstrain':1.2,'strain_hoop_microstrain':15,
          'temperature_k':3,'wetness_index':0.35}


def load_rows(path: Path):
    with path.open(encoding='utf-8') as stream:
        rows=[]
        for row in csv.DictReader(stream):
            rows.append({k: (v.lower()=='true' if k in ('packet_valid','h2s_valid') else v if k=='h2s_status' else float(v) if v else None)
                         for k,v in row.items()})
        return rows


def assess(rows, baseline=None):
    alerts=[]
    counters={'gap':0,'coupling':0,'mechanical':0,'wet':0,'thermal':0,'flat':0}
    emitted=set()
    descriptions={
      'gap':('sensor_fault','انقطاع متكرر في حزم القياس','high'),
      'coupling':('sensor_fault','تغير كبير في اقتران السرج؛ يلزم فحص التثبيت','high'),
      'flat':('sensor_fault','ثبات قناة الحرارة رغم تغير المرجع','medium'),
      'mechanical':('mechanical','انحراف في الانفعال المحوري عن التشغيل المرجعي','high'),
      'wet':('wetness','ارتفاع مؤشر البلل عن المرجع؛ راجع الطلاء والعزل','medium'),
      'thermal':('thermal','انحراف درجة الحرارة عن المرجع','high')}
    for i,row in enumerate(rows):
        ref=baseline[i] if baseline and i<len(baseline) else None
        finite=all(row.get(c) is not None and math.isfinite(row[c]) for c in LIMITS)
        valid=row.get('packet_valid') is True and finite
        conditions={'gap':not valid,'coupling':False,'mechanical':False,'wet':False,'thermal':False,'flat':False}
        if valid and ref and ref.get('packet_valid'):
            residual={c:row[c]-ref[c] for c in LIMITS}
            conditions['coupling']=abs(residual['strain_hoop_microstrain'])>LIMITS['strain_hoop_microstrain']
            # Bending in this simulator gives opposite axial/hoop signs through
            # the Poisson response. Common-sign attenuation is not classified
            # as mechanical damage; its large change is a coupling check.
            conditions['mechanical']=(abs(residual['strain_axial_microstrain'])>LIMITS['strain_axial_microstrain']
              and residual['strain_axial_microstrain']*residual['strain_hoop_microstrain']<0
              and abs(residual['strain_hoop_microstrain'])>=0.15*abs(residual['strain_axial_microstrain'])
              and not conditions['coupling'])
            conditions['wet']=residual['wetness_index']>LIMITS['wetness_index']
            conditions['thermal']=abs(residual['temperature_k'])>LIMITS['temperature_k']
            if i>=6:
                window=rows[i-6:i+1]; refs=baseline[i-6:i+1]
                ts=[r['temperature_k'] for r in window if r.get('temperature_k') is not None]
                bs=[r['temperature_k'] for r in refs if r.get('temperature_k') is not None]
                conditions['flat']=len(ts)==7 and len(bs)==7 and max(ts)-min(ts)<1e-8 and max(bs)-min(bs)>0.015
        for kind, condition in conditions.items():
            counters[kind]=counters[kind]+1 if condition else 0
            if counters[kind]>=3 and kind not in emitted:
                category,title,priority=descriptions[kind]
                alerts.append({'category':category,'title':title,'priority':priority,
                  'sample_index':i,'simulation_time_s':row['timestamp_s'],
                  'basis':'declared_rules_paired_control' if ref else 'quality_rules',
                  'note':'نتيجة قواعد بحثية غير معايرة ميدانيًا؛ ليست تشخيص شق أو تسرب'})
                emitted.add(kind)
    usable=sum(r.get('packet_valid') is True and all(r.get(c) is not None and math.isfinite(r[c]) for c in LIMITS) for r in rows)
    quality='good' if usable/ max(len(rows),1) >=0.98 else 'degraded'
    return {'alerts':alerts,'quality':quality,'valid_count':usable,'total_count':len(rows),
      'reference_available':baseline is not None,'thresholds':LIMITS,
      'method':'قواعد بحثية مع تشغيل مرجعي مطابق' if baseline else 'فحوص جودة فقط؛ لا يوجد مرجع معتمد'}
