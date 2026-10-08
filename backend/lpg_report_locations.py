"""Locate display observations on the same illustrative route as the map.

Positions are interpolated display estimates, never claimed as field GPS fixes.
Historical legs use their own endpoints, not their replay scenario's cage route.
"""
import math
from datetime import datetime, timedelta
from urllib.parse import urlencode

LOCATION_NOTE = 'مواقع الملاحظات تقديرية على مسار العرض، وليست إحداثيات GPS مسجلة ميدانيًا.'
TITLES = {'lpg_anomaly': 'إشارة غاز قرب القفص', 'thermal_anomaly': 'تغير حراري',
          'mount_anomaly': 'تغير في تثبيت القفص', 'shock': 'صدمة أثناء النقل',
          'lock': 'فتح قفل القفص', 'missing': 'انقطاع أو نقص في القياسات'}


def route_path(journey, catalog):
    origin = catalog[journey['origin']['trip_number']][journey['origin']['kind']]['position']
    destination = catalog[journey['destination']['trip_number']][journey['destination']['kind']]['position']
    for reference in (journey['destination'], journey['origin']):
        if reference['kind'] != 'store':
            continue
        path = catalog[reference['trip_number']]['path']
        if path[0] == origin and path[-1] == destination:
            return [list(point) for point in path]
        if path[-1] == origin and path[0] == destination:
            return [list(point) for point in reversed(path)]
    # A historical inter-station leg has no road/GPS trace in the current demo.
    return [[origin[0] + (destination[0] - origin[0]) * i / 24,
             origin[1] + (destination[1] - origin[1]) * i / 24] for i in range(25)]


def point_at(path, progress):
    # Match frontend/droneFlight.ts flightPoint exactly, including reverse legs.
    t = max(0, min(1, progress)) * (len(path) - 1)
    index = min(len(path) - 2, math.floor(t))
    fraction = t - index
    return [path[index][axis] + (path[index + 1][axis] - path[index][axis]) * fraction
            for axis in (0, 1)]


def distance_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, value))))


def runs(rows, predicate):
    group = []
    for row in rows:
        if predicate(row):
            if group and row['timestamp_s'] - group[-1]['timestamp_s'] > 5:
                yield group
                group = []
            group.append(row)
        elif group:
            yield group
            group = []
    if group:
        yield group


def located_observations(journey, evidence, catalog):
    path = route_path(journey, catalog)
    cities = {city['name']: city for item in catalog.values() for city in item['cities']}
    events = []
    rows = evidence['rows']
    by_time = {row['timestamp_s']: row for row in rows}

    def add(kind, timestamp, value_label=''):
        location = None
        if timestamp is not None:
            progress = max(0, min(1, timestamp / journey['reading_end_s']))
            position = point_at(path, progress)
            nearest = min(cities.values(), key=lambda city: distance_km(position, city['position']))
            longitude, latitude = (round(position[0], 4), round(position[1], 4))
            location = {'longitude': longitude, 'latitude': latitude, 'nearest_city': nearest['name'],
                        'distance_km': round(distance_km(position, nearest['position']), 1),
                        'progress_percent': round(progress * 100, 1), 'source': 'estimated_display_route',
                        'maps_url': 'https://www.google.com/maps/search/?' + urlencode({
                            'api': 1, 'query': f'{latitude:.4f},{longitude:.4f}'})}
        recorded = (datetime.fromisoformat(journey['departed_at']) + timedelta(seconds=timestamp)).isoformat() if timestamp is not None else None
        events.append({'kind': kind, 'title': TITLES[kind], 'reading_elapsed_s': timestamp,
                       'recorded_at': recorded, 'value_label': value_label, 'location': location})

    for alert in evidence['alerts']:
        kind, timestamp = alert['signal'], alert['timestamp_s']
        row = by_time.get(timestamp, {})
        key, label, unit, digits = {
            'lpg_anomaly': ('lpg_ppm', 'LPG', 'ppm', 4),
            'thermal_anomaly': ('mount_temperature_C', 'الحرارة', '°C', 1),
            'mount_anomaly': ('mount_strain_a', 'انفعال التثبيت', 'microstrain', 1),
        }[kind]
        value = row.get(key)
        add(kind, timestamp, f'{label}: {value:.{digits}f} {unit}' if value is not None else 'القراءة غير متاحة')
    for group in runs(rows, lambda row: row['packet_valid'] and row['acceleration_g'] >= 1.5):
        add('shock', group[0]['timestamp_s'], f"أعلى تسارع في الواقعة: {max(row['acceleration_g'] for row in group):.1f} g")
    for group in runs(rows, lambda row: row['packet_valid'] and not row['latch_closed']):
        add('lock', group[0]['timestamp_s'], 'فتح القفل أثناء فترة المراقبة')
    # Locate the incomplete-monitoring note already shown in the summary.
    # Brief tolerated packet gaps must not become new customer fault claims.
    gaps = list(runs(rows, lambda row: not row['packet_valid'] or not row['lpg_valid'])) if evidence['incomplete'] else []
    for group in gaps:
        add('missing', group[0]['timestamp_s'], 'بداية نقص القياسات في السجل')
    if evidence['incomplete'] and not gaps:
        add('missing', rows[-1]['timestamp_s'] if rows else None,
            'القياسات المتاحة لا تكفي؛ الموقع لآخر قراءة' if rows else 'لا تتوفر قراءة لتحديد الموقع')
    events.sort(key=lambda event: (event['reading_elapsed_s'] is None, event['reading_elapsed_s'] or 0, event['kind']))
    for index, event in enumerate(events, 1):
        event['id'] = f"{journey['id']}-OBS-{index:02d}"
        event['marker'] = index
    return path, events
