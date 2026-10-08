"""Shipment-only inspection requests and assessments with audited persistence."""
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .lpg_cylinders import cylinder_passport, journey_evidence
from .store import now, uid

KIND = 'lpg_inspections'
STATES = {'new': ['in_progress', 'cancelled'],
          'in_progress': ['review', 'cancelled'],
          'review': ['review', 'in_progress', 'closed'], 'closed': [], 'cancelled': []}
CONDITIONS = {'pending', 'normal', 'maintenance', 'isolate', 'undetermined'}


class ShipmentInspectionRequest(BaseModel):
    number: int = Field(ge=1, le=21)
    reason: str = Field(min_length=3, max_length=2000)
    priority: Literal['urgent', 'high', 'normal'] = 'normal'
    evidence_until_s: int = Field(default=1200, ge=0, le=1200)
    scheduled_at: str = Field(default='', max_length=60)

    @field_validator('reason')
    @classmethod
    def reason_text(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('اكتب سبب الفحص')
        return value.strip()

    @field_validator('scheduled_at')
    @classmethod
    def schedule(cls, value):
        if value:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError('حدد منطقة زمنية للموعد')
        return value


class ShipmentInspectionTransition(BaseModel):
    status: Literal['in_progress', 'review', 'closed', 'cancelled']
    assignee: str = Field(default='', max_length=100)
    condition: Literal['pending', 'normal', 'maintenance', 'isolate', 'undetermined'] = 'pending'
    findings: str = Field(default='', max_length=4000)
    recommendation: str = Field(default='', max_length=2000)
    gas_check: Literal['not_checked', 'no_indication', 'indication', 'inconclusive'] = 'not_checked'
    mount_check: Literal['not_checked', 'normal', 'loose', 'damaged'] = 'not_checked'
    latch_check: Literal['not_checked', 'normal', 'damaged'] = 'not_checked'
    decision: str = Field(default='', max_length=2000)


def ensure_demo_inspections(store):
    seeds = [
        (2, 'new', 'high', 550, 'مراجعة انفعال التثبيت وفتح القفل أثناء رحلة التوزيع.'),
        (8, 'in_progress', 'urgent', 650, 'فحص منطقة القفص والوصلات بعد إشارة LPG مؤكدة في قراءات السراج.'),
        (14, 'closed', 'high', 480, 'مراجعة موضع حساس الحرارة وتأثره بالتعرض الحراري.'),
        (20, 'review', 'urgent', 620, 'فحص منطقة القفص بعد إشارة LPG وتغير في التثبيت.'),
        (6, 'new', 'normal', 420, 'التحقق من اتصال السراج والطاقة بسبب نقص القياسات.'),
        (17, 'in_progress', 'normal', 800, 'التحقق من جودة القياسات واتصال بوابة الشاحنة.'),
    ]
    for number, status, priority, cutoff, reason in seeds:
        task_id = f'LPG-F-{number:03d}'
        if store.get(KIND, task_id):
            continue
        task = {'id': task_id, 'saddle_id': f'S-{number}', 'trip_id': f'TRIP-{number:03d}',
                'number': number, 'reason': reason, 'priority': priority, 'status': status,
                'condition': 'pending', 'assignee': '' if status == 'new' else 'مفتش العرض',
                'created_at': '2026-10-08T09:00:00+03:00', 'scheduled_at': '2026-10-08T11:00:00+03:00',
                'requested_by': 'سيناريو العرض', 'source': 'display_scenario',
                'evidence_until_s': cutoff, 'assessment': None, 'decision': '',
                'history': [{'status': 'new', 'at': '2026-10-08T09:00:00+03:00', 'actor': 'سيناريو العرض', 'note': 'طلب فحص توضيحي لسراج الشحنة.'}]}
        if status != 'new':
            task['history'].append({'status': 'in_progress', 'at': '2026-10-08T09:30:00+03:00', 'actor': 'مفتش العرض', 'note': 'بدء الفحص في سيناريو العرض.'})
        if status in ('review', 'closed'):
            task['condition'] = 'isolate' if number == 20 else 'normal'
            task['assessment'] = {'condition': task['condition'],
                'findings': 'تقييم توضيحي: تحتاج منطقة القفص إلى تحديد مصدر إشارة LPG بالفحص الفردي.' if number == 20 else 'تقييم توضيحي: تمت مراجعة رقعة الحرارة والتثبيت، ولم تسجل ملاحظة ظاهرية بعد المراجعة.',
                'recommendation': 'إبقاء القفص معزولًا حتى استكمال التحقق.' if number == 20 else 'متابعة الحرارة في دورة النقل التالية.',
                'gas_check': 'inconclusive' if number == 20 else 'no_indication', 'mount_check': 'normal', 'latch_check': 'normal',
                'at': '2026-10-08T10:15:00+03:00', 'by': 'مفتش العرض', 'source': 'display_scenario'}
            task['history'].append({'status': 'review', 'at': task['assessment']['at'], 'actor': 'مفتش العرض', 'note': task['assessment']['findings']})
        if status == 'closed':
            task['decision'] = 'قرار توضيحي: إغلاق مهمة المراجعة مع استمرار متابعة الحرارة.'
            task['history'].append({'status': 'closed', 'at': '2026-10-08T10:45:00+03:00', 'actor': 'مفتش العرض', 'note': task['decision']})
        store.put(KIND, task, actor='demo_seed', action='seed_shipment_inspection')


def create_request(store, body: ShipmentInspectionRequest, actor):
    timestamp = now()
    task = {'id': uid('LPG-F'), 'number': body.number, 'saddle_id': f'S-{body.number}',
            'trip_id': f'TRIP-{body.number:03d}', 'status': 'new', 'condition': 'pending',
            'reason': body.reason, 'priority': body.priority, 'scheduled_at': body.scheduled_at,
            'evidence_until_s': body.evidence_until_s, 'created_at': timestamp, 'updated_at': timestamp,
            'requested_by': actor, 'source': 'display_scenario', 'assignee': '',
            'assessment': None, 'decision': '', 'history': [{'status': 'new', 'at': timestamp, 'actor': actor, 'note': body.reason}]}
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = [json.loads(r['body']) for r in db.execute('SELECT body FROM entities WHERE kind=?', (KIND,))]
        if any(t['trip_id'] == task['trip_id'] and t['status'] not in ('closed', 'cancelled') for t in existing):
            raise ValueError('يوجد طلب فحص مفتوح لهذه الرحلة؛ افتحه من القائمة.')
        store.write(db, KIND, task, actor, 'create_shipment_inspection')
    return task


def transition_request(store, task_id, body: ShipmentInspectionTransition, actor):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT body FROM entities WHERE kind=? AND id=?', (KIND, task_id)).fetchone()
        if not row:
            raise KeyError(task_id)
        task = json.loads(row['body'])
        if body.status not in STATES[task['status']]:
            raise ValueError('تغيرت حالة المهمة أو أن الإجراء غير مسموح في حالتها الحالية.')
        timestamp = now()
        note = ''
        if body.status == 'in_progress':
            if not body.assignee.strip():
                raise ValueError('حدد اسم المفتش')
            task['assignee'] = body.assignee.strip()
            note = 'بدء الفحص' if task['status'] == 'new' else 'إعادة الفحص؛ التقييم السابق محفوظ للمراجعة.'
        elif body.status == 'review':
            if body.condition == 'pending' or len(body.findings.strip()) < 3 or len(body.recommendation.strip()) < 3:
                raise ValueError('حدد تقييم الحالة واكتب النتيجة والتوصية')
            if body.condition == 'normal' and (body.gas_check != 'no_indication' or body.mount_check != 'normal' or body.latch_check != 'normal'):
                raise ValueError('تقييم الحالة دون ملاحظة يحتاج تسجيل نتيجة فحص LPG والتثبيت والقفل')
            task['condition'] = body.condition
            task['assessment'] = {k: getattr(body, k).strip() for k in ('condition', 'findings', 'recommendation', 'gas_check', 'mount_check', 'latch_check')}
            task['assessment'].update(at=timestamp, by=actor, source='manual_demo_assessment')
            note = body.findings.strip()
        elif body.status in ('closed', 'cancelled'):
            if len(body.decision.strip()) < 3:
                raise ValueError('اكتب القرار أو سبب الإلغاء')
            if body.status == 'closed' and not task['assessment']:
                raise ValueError('لا يمكن إغلاق المهمة قبل تسجيل تقييم')
            task['decision'] = body.decision.strip()
            note = task['decision']
        task.update(status=body.status, updated_at=timestamp)
        task['history'].append({'status': body.status, 'at': timestamp, 'actor': actor, 'note': note})
        store.write(db, KIND, task, actor, f'shipment_inspection:{body.status}')
    return task


def inspection_evidence(task):
    serial = f"CYL-{task['number']:03d}-01"
    journey = cylinder_passport(serial)['journeys'][-1]
    evidence = journey_evidence(serial, journey['id'], task['evidence_until_s'])
    # The task belongs to the whole Seraj-monitored cage, not its first cylinder.
    return {k: v for k, v in evidence.items() if k not in ('serial', 'journey_id', 'rows')}
