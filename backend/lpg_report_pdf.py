"""Arabic customer summary, located observations, and locally generated QR."""
import math
from io import BytesIO
from pathlib import Path
from threading import Lock

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT = 'QaifArabic'
INK, MUTED, LINE = '#38357D', '#74718C', '#E3E1EF'
_font_lock = Lock()


def _font():
    with _font_lock:
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT, str(Path(__file__).parent / 'assets' / 'IBMPlexSansArabic-Regular.ttf')))


def qr_drawing(url, size=84):
    qr = QrCodeWidget(url, barLevel='M')
    x1, y1, x2, y2 = qr.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2-x1), 0, 0, size / (y2-y1), 0, 0])
    drawing.add(qr)
    return drawing


def qr_svg(url):
    return renderSVG.drawToString(qr_drawing(url, 180)).encode('utf-8')


def report_pdf(report, url):
    _font()
    stream = BytesIO()
    c = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    c.setTitle(f"قائف - تقرير الأسطوانة {report['serial']}")
    c.setAuthor('قائف')
    right, left = A4[0]-40, 40

    def visual(value):
        return get_display(arabic_reshaper.reshape(str(value)))

    def text(value, y, size=10, color=INK, x=right):
        c.setFillColor(HexColor(color)); c.setFont(FONT, size)
        c.drawRightString(x, y, visual(value))

    def paragraph(value, y, width=right-left, size=9, leading=14, color=MUTED, x=right):
        words = str(value).split(); line = ''
        for word in words:
            trial = f'{line} {word}'.strip()
            if line and pdfmetrics.stringWidth(visual(trial), FONT, size) > width:
                text(line, y, size, color, x); y -= leading; line = word
            else:
                line = trial
        if line:
            text(line, y, size, color, x); y -= leading
        return y

    def box(x, y, width, height, fill='#F7F6FC', border=LINE):
        c.setFillColor(HexColor(fill)); c.setStrokeColor(HexColor(border)); c.setLineWidth(.6)
        c.roundRect(x, y, width, height, 8, stroke=1, fill=1)

    def date(value):
        return value[:10] if value else 'في الطريق'

    groups = [j for j in reversed(report['journeys']) if j.get('observations')]
    observation_count = sum(len(j['observations']) for j in groups)

    text('قائف', 804, 19)
    text('تقرير الأسطوانة للعميل', 777, 20)
    text(report['serial'], 754, 14)
    text('بيانات عرض توضيحية', 735, 9, MUTED)
    # Orange cylinder illustration; the serial stays text in the header.
    c.setFillColor(HexColor('#FA965A')); c.setStrokeColor(HexColor('#D67A40'))
    c.roundRect(64, 744, 38, 52, 12, stroke=1, fill=1)
    c.roundRect(73, 794, 20, 12, 3, stroke=1, fill=1)
    c.setStrokeColor(HexColor('#FFF5ED')); c.line(71, 767, 95, 767)

    code = report['status']['code']
    caution = code in ('review', 'pending', 'isolate', 'maintenance')
    box(left, 651, right-left, 69, '#FFF3F3' if caution else '#F3F1FD')
    text(report['status']['label'], 696, 13, x=right-14)
    paragraph(report['status']['description'], 676, right-left-28, 9, x=right-14)

    metrics = [('وجهة الرحلة الحالية', report['destination']['city']), ('رحلات مسجلة', str(report['journey_count'])), ('سعة التعبئة الاسمية', f"{report['nominal_fill_kg']} كجم")]
    width = (right-left-20)/3
    for i, (label, value) in enumerate(metrics):
        x = right-width-i*(width+10)
        box(x, 586, width, 54, '#FFFFFF')
        text(label, 620, 8, MUTED, x+width-12)
        text(value, 600, 12, x=x+width-12)
    text(f"المسار العام: {' ← '.join(report['regions'])}", 566, 10)
    text(report['current_location'], 549, 9, MUTED)

    text('تاريخ انتقال الأسطوانة', 522, 13)
    c.setStrokeColor(HexColor(LINE)); c.line(left, 511, right, 511)
    text('تاريخ الانطلاق', 495, 8, MUTED, right)
    text('من / إلى', 495, 8, MUTED, 441)
    text('نوع التنقل', 495, 8, MUTED, 199)
    text('الوصول', 495, 8, MUTED, 114)
    y = 479
    for j in report['journeys']:
        text(date(j['departed_at']), y, 8.5, x=right)
        text(j['origin']['name'], y, 9, x=441)
        text(f"إلى {j['destination']['name']}", y-15, 9, MUTED, 441)
        text(j['kind_label'], y, 8, x=199)
        text(date(j['arrived_at']), y, 8, '#A54459' if j['current'] else MUTED, 114)
        c.setStrokeColor(HexColor(LINE)); c.line(left, y-24, right, y-24)
        y -= 42

    if observation_count:
        text(f'أماكن {observation_count} ملاحظات موضحة في الصفحات التالية', 228, 8, MUTED)
    text('ملخص مراقبة الرحلة الحالية', 210, 12)
    transport = report['transport']
    peak = transport['temperature_peak_c']
    temperature = f'{peak:.1f} °C' if peak is not None else 'غير متاح'
    text(f"أعلى حرارة: \u200e{temperature}\u200e   |   مؤشر الغاز: {transport['lpg_indicator']}", 190, 9)
    note_y = 170
    for note in transport['notes']:
        note_y = paragraph(note, note_y, 390, 8.5, 12)
    if report['inspection']:
        paragraph(f"فحص سراج الرحلة: {report['inspection']['status']}", min(note_y-2, 116), 390, 8.5, 12)
    text(f"لقطة القراءات: {transport['reading_at'][:19].replace('T', ' ')} (+03:00)", 78, 8, MUTED)
    text('امسح الرمز لفتح التقرير الحالي', 63, 8, MUTED)
    renderPDF.draw(qr_drawing(url, 80), c, left-3, 63)
    c.linkURL(url, (left, 63, left+80, 143), relative=0)
    paragraph(report['disclosure'], 40, right-left, 7.5, 11)
    text(str(c.getPageNumber()), 12, 7, MUTED)
    c.showPage()

    def details_header():
        text('قائف', 804, 16)
        text('مواقع الملاحظات أثناء النقل', 777, 19)
        text(report['serial'], 754, 12)
        paragraph('لكل ملاحظة: توقيت القراءة، أقرب مدينة، الإحداثيات ورابط فتح الموقع.', 733, size=9)
        paragraph(report['observation_location_note'], 715, size=8, leading=12)
        return 684

    def details_footer():
        c.setStrokeColor(HexColor(LINE)); c.line(left, 77, right, 77)
        paragraph('الملاحظات تخص سراج القفص المشترك؛ الفحص الفردي يحدد مصدر المشكلة وحالة الأسطوانة.', 62, size=8, leading=12)
        text(str(c.getPageNumber()), 29, 8, MUTED)

    def group_header(journey, y, continued=False):
        current = 'الرحلة الحالية' if journey['current'] else 'رحلة سابقة'
        text(current + (' · تابع' if continued else ''), y, 12)
        c.setFillColor(HexColor(MUTED)); c.setFont('Helvetica', 9)
        c.drawString(left+12, y, date(journey['departed_at']))
        y = paragraph(f"{journey['origin']['name']} ← {journey['destination']['name']}", y-19, size=9, leading=13)
        text(journey['id'], y-1, 7.5, MUTED)
        return y-18

    def route_map(journey, top):
        height = 116
        box(left, top-height, right-left, height, '#F7F6FC')
        path = journey['route']['path']
        cosine = math.cos(math.radians(sum(p[1] for p in path)/len(path)))
        projected = [(p[0]*cosine, p[1]) for p in path]
        min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
        min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
        scale = min((right-left-100)/max(max_x-min_x, .02), (height-44)/max(max_y-min_y, .02))
        center_x, center_y = (min_x+max_x)/2, (min_y+max_y)/2

        def pixel(position):
            return ((left+right)/2 + (position[0]*cosine-center_x)*scale,
                    top-height/2 + (position[1]-center_y)*scale)

        c.setStrokeColor(HexColor('#E6E3F2')); c.setLineWidth(.5)
        for offset in (1, 2, 3):
            gy = top-height+offset*height/4
            c.line(left+12, gy, right-12, gy)
        c.setStrokeColor(HexColor('#8175CA')); c.setLineWidth(2)
        drawing = c.beginPath()
        for index, position in enumerate(path):
            x, y = pixel(position)
            drawing.moveTo(x, y) if index == 0 else drawing.lineTo(x, y)
        c.drawPath(drawing)
        for position, label in ((path[0], 'الانطلاق'), (path[-1], 'الوجهة')):
            x, y = pixel(position)
            c.setFillColor(HexColor(INK)); c.circle(x, y, 3, stroke=0, fill=1)
            text(label, y-3, 8, MUTED, x-10)
        badges = []
        for event in journey['observations']:
            location = event['location']
            if not location:
                continue
            x, y = pixel([location['longitude'], location['latitude']])
            bx, by = x+17, y+10
            while any(math.hypot(bx-px, by-py) < 23 for px, py in badges):
                bx += 24
                if bx > right-24:
                    bx, by = x+17, by-24
            bx = min(right-16, max(left+16, bx))
            by = min(top-12, max(top-height+12, by))
            badges.append((bx, by))
            c.setStrokeColor(HexColor('#B7435A')); c.setLineWidth(.8); c.line(x, y, bx, by)
            c.setFillColor(HexColor('#B7435A')); c.circle(x, y, 2, stroke=0, fill=1)
            c.circle(bx, by, 8, stroke=0, fill=1)
            c.setFillColor(HexColor('#FFFFFF')); c.setFont('Helvetica-Bold', 8)
            c.drawCentredString(bx, by-3, str(event['marker']))
        text('مسار تقديري · العلامات تطابق أرقام الملاحظات أدناه', top-height+7, 7, MUTED, right-10)
        return top-height-17

    def observation_row(event, y):
        box(left, y-60, right-left, 60, '#FFFFFF')
        location = event['location']
        text(f"{event['marker']}. {event['title']}", y-16, 10, INK, right-12)
        if event['recorded_at']:
            stamp = event['recorded_at'][:19].replace('T', ' ')
            c.setFillColor(HexColor(MUTED)); c.setFont('Helvetica', 7.5)
            c.drawString(left+12, y-15, stamp + ' (+03)')
        else:
            text('لم يتوفر توقيت القراءة', y-15, 8, MUTED, left+180)
        if location:
            city = f"أقرب مدينة: {location['nearest_city']} ({location['distance_km']:.1f} كم)"
            text(city, y-33, 8.5, MUTED, right-12)
            text(event['value_label'], y-33, 8, MUTED, left+197)
            c.setFillColor(HexColor(INK)); c.setFont('Helvetica', 8)
            c.drawRightString(right-12, y-49,
                f"N {location['latitude']:.4f}   |   E {location['longitude']:.4f}   |   {location['progress_percent']:.1f}%")
            text('فتح الموقع على الخريطة', y-49, 8.5, '#6657BD', left+127)
            c.linkURL(location['maps_url'], (left+12, y-53, left+136, y-38), relative=0)
        else:
            text('الموقع غير متاح لغياب القراءات؛ لم تُختلق إحداثيات لهذه الملاحظة.', y-33, 8.5, MUTED, right-12)
        return y-68

    if groups:
        y = details_header()
        map_drawn = False
        for journey in groups:
            required = 112 if map_drawn else 256
            if y-required < 90:
                details_footer(); c.showPage(); y = details_header()
            y = group_header(journey, y)
            if not map_drawn:
                y = route_map(journey, y)
                map_drawn = True
            for event in journey['observations']:
                if y-60 < 91:
                    details_footer(); c.showPage(); y = group_header(journey, details_header(), True)
                y = observation_row(event, y)
            y -= 19
        details_footer(); c.showPage()
    c.save()
    return stream.getvalue()
