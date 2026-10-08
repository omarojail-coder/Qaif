"""Public route descriptions; drawing geometry and deployment are schematic.

This is a documented subset of Saudi infrastructure, not an operator GIS inventory.
No sensors or readings are created by adding a route.
"""
SOURCE = 'https://www.aramco.com/-/media/publications/corporate-reports/bonds/2024-gmtn-prospectus.pdf#page=133'
BOOK = 'https://www.aramco.com/-/media/publications/books/energy-to-the-world/saudi-aramco-energy-to-the-world---vol2.pdf'

# Named stations give the metro diagram topology. Screen coordinates are display
# positions, never coordinates for dispatch or distance calculation.
STATIONS = {
    'yanbu': ['ينبع', 155, 340], 'central': ['القطاع الأوسط', 390, 275],
    'abqaiq': ['بقيق', 640, 340], 'qatif': ['القطيف', 640, 235],
    'rt': ['رأس تنورة', 760, 205], 'jubail': ['الجبيل', 705, 140],
    'hawiyah': ['الحوية', 590, 435], 'haradh': ['حرض', 535, 490],
    'shaybah': ['الشيبة', 820, 500], 'bahrain': ['البحرين', 850, 335],
    'qaisumah': ['القيصومة', 535, 115], 'rafha': ['رفحاء', 395, 115],
    'arar': ['عرعر', 260, 115], 'turaif': ['طريف', 130, 115],
}

CATALOG = [
    dict(id='P-1', name='خط الجبيل · مسار العرض', medium='gas', color='#A98CF6',
         station_ids=['haradh', 'hawiyah', 'abqaiq', 'jubail'],
         metro_points=[[535,490],[590,435],[590,390],[640,340],[640,205],[705,140]],
         source='illustrative_route', source_url=None, length_km=None, lifecycle='demo',
         note='مسار الغاز في النسخة التجريبية؛ لا يمثل حصرًا أو مسارًا تشغيليًا معتمدًا.'),
    dict(id='P-2', name='شرق–غرب · بترولاين', medium='oil', color='#6772E8',
         station_ids=['abqaiq', 'central', 'yanbu'],
         metro_points=[[640,340],[570,340],[505,275],[275,275],[210,340],[155,340]],
         points=[[49.67,25.92],[46.5,25.1],[42.0,24.6],[38.04,24.08]],
         source='public_route', source_url=SOURCE, source_title='أرامكو · البنية الرئيسية 2023',
         length_km=1200, length_source_url='https://www.aramcolife.com/en/publications/the-arabian-sun/articles/2021/week-25/east-west-pipelines-compounds', lifecycle='public_documented',
         note='الطول المنشور 1200 كم. يمتد من منشآت المنطقة الشرقية إلى ينبع؛ المحطات الوسيطة والرسم مبسطان.'),
    dict(id='P-3', name='بقيق–رأس تنورة', medium='oil', color='#F280A4',
         station_ids=['abqaiq', 'qatif', 'rt'],
         metro_points=[[640,340],[640,235],[670,205],[760,205]],
         points=[[49.67,25.92],[50.0,26.55],[50.14,26.65]],
         source='public_route', source_url='https://archive.aramcoworld.com/issue/196905/qa-5.htm',
         source_title='Aramco World · شبكة بقيق والقطيف', length_km=None,
         lifecycle='public_documented', note='اتصال موثق تاريخيًا؛ حالة التشغيل الحالية غير متحققة.'),
    dict(id='P-4', name='الشيبة–بقيق', medium='oil', color='#FA965A',
         station_ids=['shaybah', 'abqaiq'], metro_points=[[820,500],[800,500],[640,340]],
         points=[[54.0,22.52],[51.6,24.2],[49.67,25.92]],
         source='public_route', source_url=BOOK, source_title='أرامكو · Energy to the World، المجلد الثاني',
         length_km=645, lifecycle='public_documented', note='الطول المنشور 645 كم؛ مواضع التخطيط لا تمثل تركيبًا فعليًا.'),
    dict(id='P-5', name='القطيف–بقيق', medium='oil', color='#D57B7D',
         station_ids=['qatif', 'abqaiq'], metro_points=[[640,235],[628,247],[628,328],[640,340]],
         points=[[50.0,26.55],[49.67,25.92]], source='public_route',
         source_url='https://www.aramcolife.com/en/publications/the-arabian-sun/articles/2021/week-18/hot-tap-in-northern-area',
         source_title='Aramco Life · خط الخام القطيف–بقيق', length_km=None,
         lifecycle='public_documented', note='اسم الاتصال موثق؛ نقاط الرسم ليست إحداثيات تشغيلية.'),
    dict(id='P-6', name='AB-4 · بقيق–البحرين', medium='oil', color='#A98CF6',
         station_ids=['abqaiq', 'bahrain'], metro_points=[[640,340],[698,398],[787,398],[850,335]],
         points=[[49.67,25.92],[50.25,26.1],[50.61,26.15]], source='public_route',
         source_url='https://www.aramco.com/en/news-media/news/2018/bapco-new-pipeline',
         source_title='أرامكو · تشغيل AB-4 عام 2018', length_km=42, lifecycle='public_documented',
         note='42 كم هو الجزء البري السعودي فقط؛ امتداد البحر والبحرين ظاهر للاتصال وغير داخل التخطيط السعودي.'),
    dict(id='P-7', name='حرض–الحوية · غاز', medium='gas', color='#F280A4',
         station_ids=['haradh', 'hawiyah'], metro_points=[[535,490],[527,482],[527,475],[582,420],[590,420],[590,435]],
         points=[[49.05,24.1],[49.38,25.13]], source='public_route',
         source_url='https://www.aramco.com/en/news-media/news/2017/oil-and-gas-agreements',
         source_title='أرامكو · شبكة التدفق الحر 2017', length_km=None, lifecycle='public_documented',
         note='اتصال ضمن شبكة غاز معلنة؛ ليست 450 كم طول هذا الخط منفردًا.'),
    dict(id='P-8', name='التابلاين · تاريخي', medium='oil', color='#D57B7D',
         station_ids=['qatif','qaisumah','rafha','arar','turaif'],
         metro_points=[[640,235],[640,220],[535,115],[130,115]],
         points=[[50.0,26.55],[46.13,28.31],[43.49,29.63],[41.0,30.98],[38.65,31.68]],
         source='historical_route', source_url='https://www.aramco.com/en/news-media/elements-magazine/2021/the-tapline-a-legacy-of-triumph',
         source_title='أرامكو · التابلاين، إرث صناعي', length_km=None, lifecycle='decommissioned',
         note='خط تاريخي متوقف؛ مستبعد من تخطيط نقاط المراقبة والتغطية التشغيلية.'),
]


def ensure_catalog(store):
    """One-time catalog enrichment; preserve user records and saddle assignments."""
    if store.get('settings', 'pipeline-catalog-v2'):
        return
    for record in CATALOG:
        existing = store.get('pipelines', record['id']) or {}
        value = {**existing, **record, 'schematic': True, 'planning_spacing_m': 31,
                 'stations': [{'id': key, 'name': STATIONS[key][0],
                               'x': STATIONS[key][1], 'y': STATIONS[key][2]}
                              for key in record['station_ids']]}
        # Metro coordinates never substitute for missing geographic geometry.
        value.setdefault('points', [])
        store.put('pipelines', value, action='public_catalog_v2')
    store.put('settings', {'id': 'pipeline-catalog-v2', 'version': 2,
                          'coverage': 'documented_subset'}, action='catalog_version')
