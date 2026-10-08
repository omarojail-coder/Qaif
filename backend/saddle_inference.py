"""Per-saddle streaming inference from the provisionally adopted frozen bundle."""
import json
import math
from pathlib import Path

from .detector import assess
from .qaif_saddle_bundle import create_predictor
from .qaif_saddle_bundle.features import ALLOWED, SIGNALS

VERSION = 'qaif_saddle_provisional_416_v22'
HEADS = {
    'mechanical_anomaly': ('mechanical', 'استجابة انفعال مرتبطة بالشقوق', 'high'),
    'thermal_anomaly': ('thermal', 'شذوذ حراري في قراءات السرج', 'high'),
    'wetness_anomaly': ('wetness', 'ارتفاع البلل؛ يلزم مراجعة الطلاء والعزل', 'medium'),
    'h2s_anomaly': ('h2s', 'استجابة غير معتادة لقناة H₂S', 'high'),
}


def observation(row):
    # Never pass IDs, labels, context, forcing, truth or paired controls to ML.
    return {key: row.get(key, False if key == 'h2s_valid' else 'missing' if key == 'h2s_status' else None)
            for key in ALLOWED}


def unknown_signals():
    return {head: {'state': 'unknown', 'score': None, 'alarm': None} for head in SIGNALS}


class InferenceSession:
    def __init__(self, baseline_verified=False, legacy=False):
        self.predictor = create_predictor()
        self.baseline_verified = baseline_verified is True
        self.legacy = legacy
        self.last_time = None
        self.count = 0
        self.bad_cadence = False
        self.alerts = []
        self.emitted = set()
        self.history = []
        self.latest = {'signals': unknown_signals(), 'available_heads': 0, 'quality': 'insufficient'}

    def feed(self, rows):
        for row in rows:
            time = row['timestamp_s']
            if self.last_time is not None:
                if time <= self.last_time:
                    raise ValueError('زمن القراءة يجب أن يتزايد بين الدفعات')
                if not math.isclose(time - self.last_time, 5, rel_tol=.05, abs_tol=.25):
                    self.bad_cadence = True
            self.last_time = time
            self.count += 1
            if not self.baseline_verified or self.legacy or self.bad_cadence:
                self.latest = {'signals': unknown_signals(), 'available_heads': 0, 'quality': 'insufficient'}
            else:
                self.latest = self.predictor.step(observation(row))
                for head, value in self.latest['signals'].items():
                    if value['alarm'] is True and head not in self.emitted:
                        category, title, priority = HEADS[head]
                        self.alerts.append({'category': category, 'title': title, 'priority': priority,
                            'sample_index': self.count - 1, 'simulation_time_s': time,
                            'basis': 'trained_xgboost_416_v22', 'model_version': VERSION,
                            'signal': head, 'score': value['score'], 'confirmation_samples': 3,
                            'score_is_calibrated_probability': False,
                            'note': 'إشارة من النموذج المدرّب بعد 3 قراءات متتالية؛ يلزم التحقق من سببها. درجة النموذج ليست احتمالًا معايرًا.'})
                        self.emitted.add(head)
            self.history.append({'timestamp_s': time, **self.latest})

    def result(self, rows, baseline=None):
        rules = assess(rows, baseline if self.legacy else None)
        # Keep legacy unsupported scenarios explicit; quality rules stay active.
        findings = rules['alerts'] if self.legacy else [a for a in rules['alerts'] if a['category'] == 'sensor_fault']
        status = ('legacy_rules' if self.legacy else 'baseline_unverified' if not self.baseline_verified
                  else 'unsupported_cadence' if self.bad_cadence else 'warming_up' if self.count <= 24
                  else 'active' if self.latest['available_heads'] else 'insufficient_data')
        reasons = {'legacy_rules': 'سيناريو قديم تحلله قواعد المقارنة؛ لا يمثل نتيجة النموذج المدرّب.',
                   'baseline_unverified': 'يلزم تأكيد أن أول 120 ثانية تهيئة سليمة معلومة.',
                   'unsupported_cadence': 'الحزمة تتطلب قراءات كل 5 ثوانٍ تقريبًا؛ لم تُغيّر أو تُعاد معاينة القراءات.',
                   'warming_up': 'تجميع 24 قراءة للتهيئة قبل بدء الاستنتاج.',
                   'insufficient_data': 'لا توجد قناة مكتملة بما يكفي للاستنتاج.', 'active': ''}
        ai = {**self.latest, 'status': status, 'reason': reasons[status], 'model_version': VERSION,
              'baseline_verified': self.baseline_verified, 'baseline_samples': 24,
              'baseline_collected': min(self.count, 24), 'window_samples': 12,
              'prediction_threshold': .5, 'confirmation_samples': 3,
              'automatic': True, 'field_validated': False, 'score_is_calibrated_probability': False}
        method = 'نموذج XGBoost · نسخة 416' if status in ('active', 'warming_up', 'insufficient_data') else rules['method'] if self.legacy else 'فحوص الجودة؛ الاستنتاج معلّق'
        return {**rules, 'alerts': [*findings, *self.alerts], 'method': method, 'ai': ai}


class SaddleInference:
    def __init__(self):
        self.sessions = {}
        self.manifest = json.loads((Path(__file__).parent/'qaif_saddle_bundle/model_manifest.json').read_text())
        # Fail startup on a broken model rather than claiming an active AI.
        create_predictor()

    def session(self, saddle_id, episode_id, existing_rows=None, baseline_verified=False, legacy=False):
        cached = self.sessions.get(saddle_id)
        if cached and cached[0] == episode_id:
            return cached[1]
        value = InferenceSession(baseline_verified, legacy)
        if existing_rows:
            value.feed(existing_rows)
        self.sessions[saddle_id] = (episode_id, value)
        return value

    def config(self):
        return {'connected': True, 'automatic': True, 'model_version': VERSION,
                'mechanical_training_cases': 416, 'baseline_samples': 24,
                'sample_interval_s': 5, 'window_samples': 12, 'confirmation_samples': 3,
                'heads': list(SIGNALS), 'field_validated': False}
