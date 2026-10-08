"""Whitelisted customer summaries of the existing demonstration passports.

No operator notes, identities, raw readings, model scores or auth data are public.
The serializer and PDF use the same summary and frozen reading cutoff.
"""
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from .lpg_cylinders import cylinder_passport, identity, journey_evidence
from .lpg_report_locations import located_observations, LOCATION_NOTE

ASSETS = Path(__file__).parent / 'assets'
KINDS = {'delivery': 'توزيع إلى متجر', 'return': 'إعادة إلى غازكو', 'transfer': 'نقل بين المناطق'}
DISCLOSURE = 'بيانات عرض توضيحية. الحالة مبنية على قراءات سراج القفص المشترك والفحص المسجل للرحلة، ولا تُعد شهادة سلامة أو فحصًا فرديًا للأسطوانة.'


@lru_cache(maxsize=1)
def places():
    return {item['number']: item for item in json.loads((ASSETS / 'lpg-report-places.json').read_text(encoding='utf-8'))}


def normalize_serial(serial):
    value = serial.strip().upper()
    identity(value)
    return value


def _place(reference):
    return dict(places()[reference['trip_number']][reference['kind']])


def _observation(evidence):
    notes = []
    if evidence['signals']['lpg_anomaly']['confirmed']:
        notes.append('سُجلت إشارة غاز قرب القفص؛ مصدرها يحتاج تحديدًا بالفحص.')
    if evidence['signals']['thermal_anomaly']['confirmed']:
        notes.append('سُجل تغير حراري يستدعي مراجعة ظروف النقل.')
    if evidence['signals']['mount_anomaly']['confirmed']:
        notes.append('سُجل تغير في تثبيت القفص أثناء النقل.')
    if evidence['shock_events']:
        notes.append('سُجلت صدمة نقل في قراءات القفص.')
    if evidence['lock_open_events']:
        notes.append('سُجل فتح لقفل القفص أثناء المراقبة.')
    if evidence['incomplete']:
        notes.append('المراقبة غير مكتملة بسبب نقص القياسات.')
    return notes or ['لا توجد ملاحظة في قراءات النقل المتاحة.']


def customer_report(serial, inspections=()):
    serial = normalize_serial(serial)
    number, _ = identity(serial)
    passport = cylinder_passport(serial)
    current = passport['journeys'][-1]
    tasks = [t for t in inspections if t.get('trip_id') == passport['current_trip_id'] and t.get('status') != 'cancelled']
    task = max(tasks, key=lambda t: t.get('updated_at') or t['created_at'], default=None)
    cutoff = int(places()[number]['initial_progress'] * 240) * 5
    if task:
        cutoff = max(cutoff, min(1200, max(0, int(task.get('evidence_until_s', 0)))))
    evidence = journey_evidence(serial, current['id'], cutoff)
    state = evidence['expected_state']
    status = {
        'clear': ('لا ملاحظة في القراءات المتاحة', 'لم تسجل مراقبة الرحلة الحالية ملاحظة تستدعي المراجعة.'),
        'review': ('تحتاج مراجعة الرحلة', 'توجد ملاحظة على سراج القفص المشترك تحتاج إلى التحقق.'),
        'unknown': ('المراقبة غير مكتملة', 'القراءات المتاحة لا تكفي لتقدير الحالة الحالية.'),
    }[state]
    assessment = None
    if task:
        condition = task.get('condition', 'pending')
        # A prior assessment retained during reinspection is not a current release.
        reviewed = task['status'] in ('review', 'closed')
        if reviewed and condition in ('isolate', 'maintenance'):
            state = condition
            status = ('القفص معزول للمراجعة', 'فحص سراج الرحلة سجل حاجة إلى عزل القفص حتى استكمال التحقق.') if condition == 'isolate' else ('تحتاج الرحلة إلى متابعة صيانة', 'فحص سراج الرحلة سجل ملاحظة تحتاج متابعة الصيانة.')
        elif reviewed and condition == 'normal' and task['status'] == 'closed':
            state, status = 'reviewed', ('اكتملت مراجعة سراج الرحلة', 'أُغلقت المراجعة دون ملاحظة في الفحص المسجل لسراج الرحلة.')
        elif task['status'] not in ('closed', 'cancelled'):
            state, status = 'pending', ('فحص الرحلة قيد المتابعة', 'طلب فحص سراج الرحلة لم يُغلق بعد؛ الحالة الفردية للأسطوانة غير محسومة.')
        assessment = {'status': 'مكتمل' if task['status'] == 'closed' else 'قيد المتابعة',
                      'at': (task.get('assessment') or {}).get('at'),
                      'summary': status[1]}

    journeys = []
    for journey in passport['journeys']:
        item_evidence = evidence if journey['current'] else journey_evidence(serial, journey['id'])
        path, observations = located_observations(journey, item_evidence, places())
        journeys.append({'id': journey['id'], 'kind': journey['kind'], 'kind_label': KINDS[journey['kind']],
            'origin': _place(journey['origin']), 'destination': _place(journey['destination']),
            'departed_at': journey['departed_at'], 'arrived_at': journey['arrived_at'],
            'current': journey['current'], 'status': 'في الطريق' if journey['current'] else 'وصلت',
            'notes': _observation(item_evidence), 'observations': observations,
            'route': {'path': path, 'source': 'estimated_display_route'}})
    regions = list(dict.fromkeys(p['region'] for j in journeys for p in (j['origin'], j['destination'])))
    read_at = (datetime.fromisoformat(current['departed_at']) + timedelta(seconds=cutoff)).isoformat()
    return {'serial': serial, 'source': 'display_scenario', 'registered_at': passport['registered_at'],
        'nominal_fill_kg': passport['nominal_fill_kg'], 'status': {'code': state, 'label': status[0], 'description': status[1]},
        'current_location': f"في الطريق من {journeys[-1]['origin']['city']} إلى {journeys[-1]['destination']['city']}",
        'origin': journeys[0]['origin'], 'destination': journeys[-1]['destination'], 'regions': regions,
        'journey_count': len(journeys), 'journeys': journeys, 'inspection': assessment,
        'transport': {'notes': _observation(evidence), 'temperature_peak_c': (evidence['peaks']['temperature'] or {}).get('value'),
                      'lpg_peak_ppm': (evidence['peaks']['lpg'] or {}).get('value'),
                      'lpg_indicator': 'إشارة تحتاج فحصًا' if evidence['signals']['lpg_anomaly']['confirmed'] else 'قراءات غير مكتملة' if evidence['incomplete'] else 'لم تُسجل إشارة مؤكدة',
                      'shock_events': evidence['shock_events'], 'reading_until_s': cutoff, 'reading_at': read_at},
        'observation_location_note': LOCATION_NOTE,
        'generated_at': datetime.now(timezone.utc).isoformat(), 'disclosure': DISCLOSURE}
