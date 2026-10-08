"""Virtual presentation flights. No aircraft control, telemetry, or operational ETA."""
import math
import time
from datetime import datetime, timezone

DISPLAY_CORRECTIONS = {
    'gas-3': ((49.7, 27.0), (49.07, 27.11)),
    'gas-9': ((49.71, 27.28), (49.31, 27.11)),
    'refinery-2': ((50.14, 26.65), (50.09207, 26.70243)),
    'refinery-5': ((39.16, 21.4), (39.18222, 21.45139)),
    'S-12': ((49.6523, 27.0321), (49.66, 27.0)),
    'S-3': ((50.14, 26.65), (50.09207, 26.70243)),
}
DURATION_S = 120


def clock_ms():
    return round(time.time() * 1000)


def display_position(record):
    lon, lat = record.get('lon'), record.get('lat')
    if (isinstance(lon, bool) or isinstance(lat, bool) or
            not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)) or
            not math.isfinite(lon) or not math.isfinite(lat) or abs(lon) > 180 or abs(lat) > 90):
        return None
    correction = DISPLAY_CORRECTIONS.get(record.get('id'))
    if correction and record.get('source') in ('illustrative_inventory', 'simulation'):
        before, after = correction
        if abs(lon - before[0]) < 1e-6 and abs(lat - before[1]) < 1e-6:
            return list(after)
    return [float(lon), float(lat)]


def distance_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    q = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, q))))


def great_circle(a, b, count=65):
    def vector(p):
        lon, lat = map(math.radians, p)
        return [math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)]
    x, y = vector(a), vector(b)
    angle = math.acos(min(1, max(-1, sum(u*v for u, v in zip(x, y)))))
    if angle < 1e-8:
        return [list(a), list(b)]
    path = []
    for i in range(count):
        t = i/(count-1)
        if abs(math.sin(angle)) < 1e-8:
            path.append([a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t])
            continue
        k, j = math.sin((1-t)*angle)/math.sin(angle), math.sin(t*angle)/math.sin(angle)
        u, v, w = [k*p+j*q for p, q in zip(x, y)]
        path.append([math.degrees(math.atan2(v, u)), math.degrees(math.atan2(w, math.hypot(u, v)))])
    path[0], path[-1] = list(a), list(b)
    return path


def make_plan(saddle, assets, start=False, at_ms=None):
    target = display_position(saddle)
    if target is None:
        return None
    candidates = [(distance_km(display_position(a), target), a, display_position(a))
                  for a in assets if a.get('type') in ('gas', 'refinery') and display_position(a) is not None]
    if not candidates:
        return None
    distance, origin, point = min(candidates, key=lambda item: (item[0], str(item[1]['id'])))
    plan = {
        'version': 1, 'source': 'virtual_display',
        'origin': {'id': origin['id'], 'name': origin['name'], 'type': origin['type'], 'position': point},
        'target': {'id': saddle['id'], 'name': saddle['name'], 'position': target},
        'path': great_circle(point, target), 'distance_km': distance,
        'duration_s': DURATION_S if distance > .001 else 0,
        'started_ms': None, 'stopped_ms': None,
    }
    return start_plan(plan, at_ms) if start else plan


def start_plan(plan, at_ms=None):
    stamp = clock_ms() if at_ms is None else at_ms
    return {**plan, 'started_ms': stamp, 'stopped_ms': None,
            'started_at': datetime.fromtimestamp(stamp/1000, timezone.utc).isoformat()}


def stop_plan(plan, at_ms=None):
    return {**plan, 'stopped_ms': clock_ms() if at_ms is None else at_ms}
