"""Eight demonstration saddle locations on the displayed pipeline corridors.

Registering a saddle creates no readings and no inference results. Existing
episodes, alerts and user-edited locations are preserved during the upgrade.
"""
VERSION = 'saddle-locations-v31'
SADDLES = [
    dict(id='S-12', name='الجبيل · السرج 12', asset_id='gas-13', pipeline_id='P-1', lon=49.6633, lat=26.6436, weld=True, wet_exposure=True),
    dict(id='S-7', name='ينبع · السرج 7', asset_id='refinery-1', pipeline_id='P-2', lon=39.115, lat=24.135, weld=False, wet_exposure=True),
    dict(id='S-3', name='رأس تنورة · السرج 3', asset_id='refinery-2', pipeline_id='P-3', lon=49.964, lat=26.63, weld=False, wet_exposure=False),
    dict(id='S-1', name='بقيق · السرج 1', asset_id='gas-11', pipeline_id='P-1', lon=49.465, lat=25.555, weld=False, wet_exposure=False),
    dict(id='S-4', name='القطاع الأوسط · السرج 4', asset_id='refinery-4', pipeline_id='P-2', lon=44.71, lat=24.435, weld=False, wet_exposure=False),
    dict(id='S-5', name='شرق بترولاين · السرج 5', asset_id='gas-11', pipeline_id='P-2', lon=47.87, lat=25.085, weld=True, wet_exposure=False),
    dict(id='S-6', name='مسار الشيبة · السرج 6', asset_id='gas-10', pipeline_id='P-4', lon=51.375, lat=23.485, weld=False, wet_exposure=False),
    dict(id='S-8', name='حرض–الحوية · السرج 8', asset_id='gas-5', pipeline_id='P-7', lon=49.195, lat=24.56, weld=True, wet_exposure=False),
]
LEGACY_LOCATIONS = {'S-12': (49.6523, 27.0321), 'S-7': (38.04, 24.08), 'S-3': (50.14, 26.65)}


def ensure_saddles(store):
    if store.get('settings', VERSION):
        return
    for record in SADDLES:
        old = store.get('saddles', record['id'])
        if old:
            previous = LEGACY_LOCATIONS.get(record['id'])
            if old.get('source') != 'simulation' or previous is None:
                continue
            if abs(old.get('lon', 0) - previous[0]) > 1e-6 or abs(old.get('lat', 0) - previous[1]) > 1e-6:
                continue
            # Update placement only. Preserve measurements and contextual facts.
            value = {**old, **{k: record[k] for k in ('lon', 'lat', 'pipeline_id')},
                     'location_source': 'demonstration_route_position'}
            store.put('saddles', value, action='saddle_route_location_v31')
        else:
            value = {**record, 'source': 'simulation', 'connection': 'replay',
                     'quality': 'no_data', 'latest': None, 'episode_id': None,
                     'prior_repair': False, 'installed': True,
                     'location_source': 'demonstration_route_position'}
            store.put('saddles', value, action='register_saddle_v31')
    store.put('settings', {'id': VERSION, 'version': 31, 'saddle_count': 8}, action='saddle_catalog_version')
