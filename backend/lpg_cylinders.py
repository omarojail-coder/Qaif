"""Stable, illustrative cylinder passports, isolated from pipe operational records.

Identity is independent of cage membership. Each historical leg replays a named
shipment scenario, and evidence is restricted to its membership window. Dates,
transfers and receiving inspections are demo records, not field observations.
"""
import re
from datetime import datetime, timedelta
from functools import lru_cache

from .lpg_demo import shipment_demo

SERIAL = re.compile(r'CYL-(\d{3})-(\d{2})')
HEADS = ('mount_anomaly', 'thermal_anomaly', 'lpg_anomaly')


def identity(serial):
    match = SERIAL.fullmatch(serial)
    if not match or not 1 <= int(match[1]) <= 21 or not 1 <= int(match[2]) <= 9:
        raise ValueError('Unknown cylinder')
    return int(match[1]), int(match[2])


def cylinder_catalog():
    return {'source': 'display_scenario', 'count': 189, 'cylinders': [
        {'serial': f'CYL-{n:03d}-{p:02d}', 'position': p,
         'current_saddle_id': f'S-{n}', 'current_trip_id': f'TRIP-{n:03d}'}
        for n in range(1, 22) for p in range(1, 10)]}


@lru_cache(maxsize=189)
def cylinder_passport(serial):
    n, position = identity(serial)
    # Earlier cycles keep this serial while changing reusable cages and regions.
    previous = (n + 6) % 21 + 1
    transfer = (n + 13) % 21 + 1
    nearby = (n - 1) // 3 * 3 + (n % 3) + 1
    station = lambda number: {'kind': 'station', 'trip_number': number}
    store = lambda number: {'kind': 'store', 'trip_number': number}
    legs = [
        (10, station(previous), store(previous), previous, 'delivery'),
        (17, store(previous), station(previous), transfer, 'return'),
        (24, station(previous), station(n), transfer, 'transfer'),
        (2, station(n), store(nearby), nearby, 'delivery'),
        (6, store(nearby), station(n), nearby, 'return'),
        (8, station(n), store(n), n, 'delivery'),
    ]
    journeys = []
    for index, (day, origin, destination, seraj, kind) in enumerate(legs):
        month = 9 if index < 3 else 10
        departure = datetime.fromisoformat(f'2026-{month:02d}-{day:02d}T08:00:00+03:00')
        arrival = departure + timedelta(minutes=150 + (n % 3) * 35 + (90 if kind == 'transfer' else 0))
        current = index == len(legs) - 1
        journeys.append({
            'id': f'J-{serial[4:]}-{index + 1:02d}',
            'trip_id': f'TRIP-{n:03d}' if current else f'LPG-2026{month:02d}{day:02d}-{seraj:02d}',
            'kind': kind, 'current': current, 'origin': origin, 'destination': destination,
            'departed_at': departure.isoformat(), 'arrived_at': None if current else arrival.isoformat(),
            'expected_arrival_at': arrival.isoformat(), 'truck': f'TRK-{100 + seraj}',
            'membership': {'cage_id': f'CAGE-{seraj:03d}', 'saddle_id': f'S-{seraj}',
                           'position': position, 'loaded_at': (departure - timedelta(minutes=15)).isoformat(),
                           'unloaded_at': None if current else (arrival + timedelta(minutes=15)).isoformat()},
            'scenario_number': seraj, 'reading_start_s': 120, 'reading_end_s': 1200,
            'arrival_inspection': None if current else {
                'status': 'released', 'note': 'فحص استلام ظاهري مسجل في سيناريو العرض؛ لا تلف ظاهر، والسماح بدورة التداول التالية.',
                'inspected_at': (arrival + timedelta(minutes=25)).isoformat(), 'source': 'display_scenario'},
        })
    return {'serial': serial, 'source': 'display_scenario', 'identity_kind': 'fixed_serial',
            'registered_at': '2026-09-10T07:30:00+03:00', 'nominal_fill_kg': 11,
            'position': position, 'current_saddle_id': f'S-{n}', 'current_trip_id': f'TRIP-{n:03d}',
            'journeys': journeys, 'persisted_operational_registry': False}


def journey_evidence(serial, journey_id, until_s=1200):
    passport = cylinder_passport(serial)
    journey = next((j for j in passport['journeys'] if j['id'] == journey_id), None)
    if journey is None:
        raise ValueError('Journey does not belong to cylinder')
    end = max(0, min(float(until_s), journey['reading_end_s'])) if journey['current'] else journey['reading_end_s']
    start = journey['reading_start_s']
    demo = shipment_demo(journey['scenario_number'])
    rows = [r for r in demo['rows'] if start <= r['timestamp_s'] <= end]
    valid = [r for r in rows if r['packet_valid']]
    history = [r for r in demo['inference_history'] if start <= r['timestamp_s'] <= end]
    alerts = [a for a in demo['alerts'] if start <= a['timestamp_s'] <= end]

    def peak(key, gas=False, absolute=False):
        candidates = [r for r in valid if r[key] is not None and (not gas or r['lpg_valid'])]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: abs(r[key]) if absolute else r[key])
        return {'value': row[key], 'timestamp_s': row['timestamp_s']}

    signals = {}
    for head in HEADS:
        measured = [h['signals'][head] for h in history if h['signals'][head]['score'] is not None]
        signals[head] = {'max_score': max((s['score'] for s in measured), default=None),
                         'confirmed': any(a['signal'] == head for a in alerts),
                         'latest_state': history[-1]['signals'][head]['state'] if history else 'unknown'}
    shocks = [r for r in valid if r['acceleration_g'] >= 1.5]
    shock_events = sum(1 for i, r in enumerate(shocks) if i == 0 or r['timestamp_s'] - shocks[i - 1]['timestamp_s'] > 5)
    opened = [r for r in valid if not r['latch_closed']]
    lock_events = sum(1 for i, r in enumerate(opened) if i == 0 or r['timestamp_s'] - opened[i - 1]['timestamp_s'] > 5)
    coverage = round(len(valid) / len(rows) * 100, 1) if rows else 0
    incomplete = not rows or coverage < 90 or not rows[-1]['packet_valid'] or any(s['latest_state'] == 'unknown' for s in signals.values())
    state = 'review' if alerts or shocks or opened else 'unknown' if incomplete else 'clear'
    return {'source': 'display_scenario', 'serial': serial, 'journey_id': journey_id,
            'saddle_id': journey['membership']['saddle_id'], 'shared_cage_evidence': True,
            'window': {'start_s': start, 'end_s': end}, 'sample_interval_s': 5,
            'sample_count': len(rows), 'valid_sample_count': len(valid), 'coverage_percent': coverage,
            'lpg_coverage_percent': round(sum(r['lpg_valid'] for r in valid) / len(rows) * 100, 1) if rows else 0,
            'expected_state': state, 'incomplete': incomplete,
            'peaks': {'temperature': peak('mount_temperature_C'), 'lpg': peak('lpg_ppm', gas=True),
                      'strain_a': peak('mount_strain_a', absolute=True), 'strain_b': peak('mount_strain_b', absolute=True),
                      'shock': peak('acceleration_g')},
            'shock_events': shock_events, 'lock_open_events': lock_events,
            'lock_open_observed_s': len(opened) * 5,
            'signals': signals, 'alerts': alerts, 'rows': rows,
            'model_source': demo['model_source'], 'lpg_model_trained': False}
