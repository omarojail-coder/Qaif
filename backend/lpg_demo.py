"""Isolated shipment display data and real inference from the frozen pipe bundle.

This adapter is intentionally a demo, not a trained LPG model. It does not write
episodes, pipe saddles, alerts, or cylinder memberships to the application's DB.
"""
import math
from functools import lru_cache
from pathlib import Path

from .detector import load_rows
from .saddle_inference import InferenceSession, VERSION

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'saddle_ai'
CASES = {2: 'ai_crack', 8: 'ai_h2s', 14: 'ai_thermal', 20: 'ai_h2s'}
SIGNALS = {'mechanical_anomaly': 'mount_anomaly',
           'thermal_anomaly': 'thermal_anomaly', 'h2s_anomaly': 'lpg_anomaly'}
TITLES = {'mount_anomaly': 'تغير في انفعال التثبيت',
          'thermal_anomaly': 'ارتفاع حراري في موضع السراج',
          'lpg_anomaly': 'ارتفاع في قناة LPG'}


def rounded(value, digits=3):
    return round(value, digits) if value is not None else None


@lru_cache(maxsize=21)
def shipment_demo(number: int):
    if not 1 <= number <= 21:
        raise ValueError('Unknown shipment demo')
    case = CASES.get(number, 'ai_reference')
    original = load_rows(FIXTURES / case / 'observed.csv')
    # Keep the verified 24-sample simulator baseline. Bring selected display
    # events forward without changing the bundle's required 5-second cadence.
    skip = 100 if case == 'ai_thermal' else 60 if case == 'ai_h2s' else 24
    source = original[:24] + original[skip:]
    source += [original[-1]] * (241 - len(source))
    session = InferenceSession(baseline_verified=True)
    readings = []
    for i, item in enumerate(source):
        row = dict(item)
        row['timestamp_s'] = i * 5.0
        if row['h2s_ppm'] is not None:
            row['h2s_ppm'] = max(0.0, row['h2s_ppm'])
        # Unrelated pipe-coating channel stays out of the shipment UI.
        row['wetness_index'] = 0.0
        if number in (6, 17) and i >= 60:
            row['packet_valid'] = False
            row['h2s_valid'] = False
            row['h2s_status'] = 'missing'
        session.feed([row])
        shock = 1.8 + number * .015 if number in CASES and i in (65, 66, 67) else .05 + .09 * abs(math.sin(i * .37 + number))
        readings.append({
            'timestamp_s': row['timestamp_s'], 'packet_valid': row['packet_valid'],
            'mount_strain_a': rounded(row['strain_hoop_microstrain']),
            'mount_strain_b': rounded(row['strain_axial_microstrain']),
            'mount_temperature_C': rounded(row['temperature_k'] - 273.15) if row['temperature_k'] is not None else None,
            # The original H2S numeric signal is an explicit LPG display proxy.
            'lpg_ppm': rounded(row['h2s_ppm'], 4), 'lpg_valid': row['h2s_valid'],
            'acceleration_g': round(shock, 3),
            'latch_closed': not (number == 2 and 65 <= i <= 68),
        })
    history = [{'timestamp_s': entry['timestamp_s'], 'quality': entry['quality'],
                'signals': {target: entry['signals'][origin] for origin, target in SIGNALS.items()}}
               for entry in session.history]
    alerts = [{'signal': SIGNALS[a['signal']], 'title': TITLES[SIGNALS[a['signal']]],
               'timestamp_s': a['simulation_time_s'], 'score': a['score'],
               'source': 'previous_xgboost_demo_adapter'}
              for a in session.alerts if a['signal'] in SIGNALS]
    return {'source': 'display_scenario', 'saddle_id': f'S-{number}',
            'trip_id': f'TRIP-{number:03d}', 'model_version': VERSION,
            'model_source': 'pipe_model_with_shipment_demo_adapter',
            'field_validated': False, 'lpg_model_trained': False,
            'sample_interval_s': 5, 'baseline_samples': 24,
            'rows': readings, 'inference_history': history, 'alerts': alerts,
            'cylinders': [{'serial': f'CYL-{number:03d}-{position:02d}',
                           'position': position} for position in range(1, 10)]}
