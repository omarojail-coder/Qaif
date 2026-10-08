from .store import now

GAS = [
 ('البري', 27.17,49.31), ('تناجيب',27.86,48.8), ('الفاضلي',27.0,49.7),
 ('حرض',24.1,49.05), ('الحوية',25.13,49.38), ('الخرسانية',27.34,49.17),
 ('مدين',28.48,35.0), ('شدقم',25.88,49.33), ('واسط',27.28,49.71),
 ('الشيبة',22.52,54.0), ('بقيق',25.92,49.67), ('العثمانية',25.19,49.26),
 ('الجُبيل',27.0,49.66), ('الفريضة',25.56,48.85)]
REFINERIES = [('ينبع',24.08,38.04), ('رأس تنورة',26.65,50.14), ('جازان',16.91,42.56),
 ('الرياض',24.57,46.88), ('جدة',21.4,39.16), ('سامرف',24.02,38.15),
 ('ساتورب',27.07,49.57), ('ياسرف',24.0,38.2), ('رابغ',22.79,39.04)]


def seed(store):
    if store.all('assets'):
        return
    for category, sites in [('gas', GAS), ('refinery', REFINERIES)]:
        for index, (name, lat, lon) in enumerate(sites):
            store.put('assets', {'id': f'{category}-{index+1}', 'name':name, 'type':category,
              'region': 'المنطقة الشرقية' if lon>47 else 'المنطقة الغربية',
              'lat':lat,'lon':lon,'source':'illustrative_inventory','monitored':False,
              'note':'دليل تجريبي؛ المواقع تقريبية ولا تعبّر عن تغطية مراقبة فعلية'}, action='seed')
    for i, (name, lat, lon, asset) in enumerate([
        ('الجبيل · السرج 12',27.0321,49.6523,'gas-13'),
        ('ينبع · السرج 7',24.08,38.04,'refinery-1'),
        ('رأس تنورة · السرج 3',26.65,50.14,'refinery-2')]):
        store.put('saddles', {'id':f'S-{[12,7,3][i]}','name':name,'asset_id':asset,
          'pipeline_id': 'P-1' if i==0 else 'P-2','lat':lat,'lon':lon,
          'source':'simulation','connection':'replay','quality':'no_data',
          'latest':None, 'episode_id':None, 'weld': i==0, 'wet_exposure':i<2,
          'prior_repair':False,'installed':True},action='seed')
    store.put('pipelines',{'id':'P-1','name':'خط الجبيل','medium':'gas',
       'points':[[49.05,24.1],[49.26,25.19],[49.67,25.92],[49.66,27.0]],'schematic':True},action='seed')
    store.put('pipelines',{'id':'P-2','name':'المسار الشرقي–الغربي','medium':'oil',
       'points':[[50.14,26.65],[49.67,25.92],[46.88,24.57],[38.04,24.08]],'schematic':True},action='seed')
    store.put('settings', {'id':'system','created_at':now(),'schema_version':1},action='seed')
