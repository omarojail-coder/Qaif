import { useEffect, useState } from 'react';
import { ArrowLeft, Check, Copy, Download, ExternalLink, FileText, History, Info, MapPin, Search, Thermometer, TriangleAlert, Truck } from 'lucide-react';
import { api } from './api';
import { GUEST_MODE } from './guestMode';
import { CylinderShape } from './LpgSaddleDashboard';
import { DISPLAY_LOCALE } from './locale';
import './lpg-customer-report.css';

type Place = { name: string; city: string; region: string };
type Observation = { id: string; title: string; recorded_at: string; value_label: string; location: { nearest_city: string; longitude: number; latitude: number; maps_url: string } | null };
type Journey = { id: string; kind_label: string; origin: Place; destination: Place; departed_at: string; arrived_at: string | null; current: boolean; status: string; notes: string[]; observations?: Observation[] };
type CustomerReport = {
  serial: string; registered_at: string; nominal_fill_kg: number;
  status: { code: string; label: string; description: string };
  current_location: string; origin: Place; destination: Place; regions: string[]; journey_count: number;
  journeys: Journey[]; inspection: { status: string; at: string | null; summary: string } | null;
  transport: { notes: string[]; temperature_peak_c: number | null; lpg_peak_ppm: number | null; lpg_indicator: string; shock_events: number; reading_until_s: number; reading_at: string };
  generated_at: string; disclosure: string; observation_location_note?: string;
};
const date = (value: string | null, time = false) => value ? new Date(value).toLocaleString(DISPLAY_LOCALE, {
  calendar: 'gregory', timeZone: 'Asia/Riyadh', dateStyle: 'medium', ...(time ? { timeStyle: 'short' as const } : {}),
}) : 'لم يُسجل الوصول بعد';
const number = (value: number | null) => value === null ? 'غير متاح' : value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: 1 });

export default function LpgCustomerReport({ requestedSerial, onSelect, standalone = false }: {
  requestedSerial: string | null; onSelect: (serial: string) => void; standalone?: boolean;
}) {
  const [report, setReport] = useState<CustomerReport | null>(null), [error, setError] = useState('');
  const [query, setQuery] = useState(requestedSerial || ''), [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0), [actionError, setActionError] = useState('');
  const [copied, setCopied] = useState(false);
  const [qr, setQr] = useState('');
  useEffect(() => {
    setQuery(requestedSerial || ''); setReport(null); setError(''); setCopied(false); setActionError('');
    setLoading(Boolean(requestedSerial));
    if (!requestedSerial) return;
    let alive = true;
    api<CustomerReport>(`/public/cylinders/${encodeURIComponent(requestedSerial)}/report`)
      .then(value => { if (alive) { setReport(value); setLoading(false); } })
      .catch(e => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [requestedSerial, retry]);
  useEffect(() => {
    if (!standalone) return;
    document.title = report ? `قائف | تقرير ${report.serial}` : 'قائف | تقرير الأسطوانة';
  }, [report, standalone]);

  const publicUrl = report ? `${location.origin}/cylinder/${report.serial}` : '';
  useEffect(() => {
    setQr('');
    if (!GUEST_MODE || !publicUrl) return;
    let alive = true;
    import('qrcode').then(module => module.toDataURL(publicUrl, { width: 240, margin: 4, errorCorrectionLevel: 'M' }))
      .then(value => { if (alive) setQr(value); }).catch(() => { if (alive) setActionError('تعذر تجهيز QR؛ رابط التقرير متاح للمشاركة.'); });
    return () => { alive = false; };
  }, [publicUrl]);
  const exportGuestPdf = async () => {
    await document.fonts.ready;
    const originalTitle = document.title;
    document.title = `Qaif-${report!.serial}`;
    window.addEventListener('afterprint', () => { document.title = originalTitle; }, { once: true });
    window.print();
  };

  return <div className={`customer-report ${standalone ? 'standalone' : ''}`} dir="rtl">
    {standalone && <div className="customer-page-title"><p>تتبّع هوية أسطوانتك</p><h1>تقرير الأسطوانة</h1><span>ملخص الحالة والمسار وتاريخ التنقل</span></div>}
    <form className="customer-search panel" onSubmit={e => { e.preventDefault(); const value = query.trim().toUpperCase(); if (value) { if (value === requestedSerial) setRetry(v => v+1); else onSelect(value); } }}>
      <label htmlFor="customer-cylinder-serial"><Search size={19}/><span>البحث برقم الأسطوانة التسلسلي</span></label>
      <div><input id="customer-cylinder-serial" autoComplete="off" spellCheck={false} maxLength={40} value={query} onChange={e => setQuery(e.target.value)} placeholder="CYL-008-01" dir="ltr" required/><button className="primary" type="submit">عرض التقرير<ArrowLeft size={17}/></button></div>
      <small>الرقم مطبوع على الأسطوانة، أو افتح التقرير بمسح رمزها.</small>
    </form>
    {loading ? <section className="panel customer-empty" role="status">جاري تجهيز تقرير الأسطوانة…</section> : error ? <section className="panel customer-empty" role="alert"><TriangleAlert size={25}/><h2>{error}</h2><p>تحقق من الرقم التسلسلي المكتوب على الأسطوانة ثم ابحث مجددًا.</p><button onClick={() => setRetry(v => v+1)}>إعادة المحاولة</button></section> : !report ? <section className="panel customer-empty"><FileText size={32}/><h2>تاريخ أسطوانتك في مكان واحد</h2><p>أدخل الرقم التسلسلي لعرض حالتها ورحلاتها من غازكو إلى المتاجر.</p></section> : <>
      <article className="panel customer-identity">
        <div className="customer-identity-copy"><p className="customer-eyebrow"><FileText size={16}/>التقرير المختصر للعميل</p><h2 dir="ltr">{report.serial}</h2>
          <div className={`customer-status ${report.status.code}`}><Info size={19}/><div><strong>{report.status.label}</strong><p>{report.status.description}</p></div></div>
          <dl className="customer-facts"><div><dt>الموقع المتوقع</dt><dd><MapPin size={16}/>{report.current_location}</dd></div><div><dt>سعة التعبئة الاسمية</dt><dd>{number(report.nominal_fill_kg)} كجم</dd></div><div><dt>بداية سجل الأسطوانة</dt><dd>{date(report.registered_at)}</dd></div></dl>
        </div>
        <figure className="customer-cylinder"><CylinderShape/><figcaption dir="ltr">{report.serial}</figcaption><span>هوية الأسطوانة</span></figure>
      </article>
      <div className="customer-report-layout"><div className="customer-main">
        <section className="panel customer-route"><h3><MapPin size={19}/>المسار العام</h3><div className="customer-region-path">{report.regions.map((region, i) => <div key={region}><span>{i+1}</span><strong>{region}</strong>{i < report.regions.length-1 && <ArrowLeft size={19}/>}</div>)}</div>
          <div className="customer-current-route"><div><small>انطلاق الرحلة الحالية</small><strong>{report.journeys.at(-1)!.origin.name}</strong></div><Truck size={25}/><div><small>الوجهة</small><strong>{report.destination.name}</strong><span>{report.destination.city}</span></div></div>
        </section>
        <section className="panel customer-history"><div className="customer-section-heading"><h3><History size={19}/>تاريخ التنقل</h3><span>{number(report.journey_count)} رحلات مسجلة</span></div>
          <ol>{report.journeys.map((j, i) => <li key={j.id} className={j.current ? 'current' : ''}><span className="customer-history-index">{i+1}</span><div className="customer-history-record"><div className="customer-trip-heading"><strong>{j.kind_label}</strong><span>{j.status}</span></div><p>{j.origin.name}<ArrowLeft size={14}/>{j.destination.name}</p><div className="customer-trip-dates"><span>انطلاق: {date(j.departed_at, true)}</span><span>وصول: {date(j.arrived_at, true)}</span></div><details><summary>ملخص ملاحظات النقل</summary><ul>{j.notes.map(note => <li key={note}>{note}</li>)}</ul></details><ul className="customer-print-notes">{j.notes.map(note => <li key={note}>{note}</li>)}</ul></div></li>)}</ol>
        </section>
        <section className="panel customer-monitoring"><h3><Thermometer size={19}/>ملخص الرحلة الحالية</h3><div className="customer-monitoring-values"><div><span>أعلى حرارة مسجلة</span><strong dir="ltr">{number(report.transport.temperature_peak_c)} {report.transport.temperature_peak_c !== null && '°C'}</strong></div><div><span>مؤشر الغاز قرب القفص</span><strong>{report.transport.lpg_indicator}</strong></div><div><span>صدمات النقل المسجلة</span><strong>{number(report.transport.shock_events)}</strong></div></div><ul>{report.transport.notes.map(note => <li key={note}>{note}</li>)}</ul>
          {report.inspection && <p className="customer-inspection-summary">فحص سراج الرحلة: <strong>{report.inspection.status}</strong>{report.inspection.at && <span> · {date(report.inspection.at)}</span>}</p>}
          <small>لقطة القراءات: {date(report.transport.reading_at, true)} · بتوقيت السعودية</small>
        </section>
        {GUEST_MODE && <section className="panel customer-observations"><h3><MapPin size={19}/>أماكن الملاحظات المسجلة</h3><p>{report.observation_location_note}</p>
          {report.journeys.map(j => <div className="customer-observation-journey" key={j.id}><h4>{j.kind_label} · {date(j.departed_at)}</h4><p>{j.origin.name} ← {j.destination.name}</p>
            {j.observations?.length ? j.observations.map(o => <article key={o.id}><strong>{o.title}</strong><span>{date(o.recorded_at, true)} · {o.value_label}</span>
              {o.location ? <><span>قرب {o.location.nearest_city} · الموقع تقديري على مسار العرض</span><span dir="ltr">{o.location.latitude.toFixed(4)} N, {o.location.longitude.toFixed(4)} E</span><a href={o.location.maps_url} target="_blank" rel="noreferrer">فتح موقع الملاحظة على الخريطة</a></> : <span>لا يتوفر موقع لهذه الملاحظة.</span>}
            </article>) : <small>لا توجد ملاحظة محددة الموقع في لقطة هذه الرحلة.</small>}
          </div>)}
        </section>}
      </div><aside className="customer-share panel"><h3>احتفظ بتقرير أسطوانتك</h3><p>امسح الرمز للعودة إلى التقرير الحالي لهذه الهوية.</p><a href={publicUrl} target={standalone ? undefined : '_blank'} rel="noreferrer" aria-label={`فتح تقرير الباركود للأسطوانة ${report.serial}`}>{!GUEST_MODE || qr ? <img src={GUEST_MODE ? qr : `/api/public/cylinders/${report.serial}/qr.svg`} width="180" height="180" alt={`رمز QR لتقرير الأسطوانة ${report.serial}`}/> : <span>جاري تجهيز QR…</span>}</a><strong dir="ltr">{report.serial}</strong>
        {GUEST_MODE ? <button className="customer-pdf-button" onClick={exportGuestPdf}><Download size={17}/>تصدير التقرير PDF</button> : <a className="button-link customer-pdf-button" href={`/api/public/cylinders/${report.serial}/report.pdf`} download={`Qaif-${report.serial}.pdf`}><Download size={17}/>تصدير التقرير PDF</a>}
        {GUEST_MODE && <small>في نافذة الطباعة اختر «حفظ بصيغة PDF». يتضمن التقرير أماكن الملاحظات وإحداثياتها.</small>}
        <button onClick={async () => { try { await navigator.clipboard.writeText(publicUrl); setCopied(true); setActionError(''); } catch { setActionError('تعذر النسخ تلقائيًا؛ يمكنك نسخ الرابط الظاهر أدناه.'); } }}>{copied ? <Check size={17}/> : <Copy size={17}/>} {copied ? 'تم نسخ الرابط' : 'نسخ رابط التقرير'}</button>
        {!standalone && <a href={publicUrl} className="button-link" target="_blank" rel="noreferrer"><ExternalLink size={16}/>عرض نافذة العميل</a>}
        <a className="customer-share-url" href={publicUrl} dir="ltr">{publicUrl}</a>
        {actionError && <p role="alert" className="customer-action-error">{actionError}</p>}{copied && <span role="status" className="customer-copy-feedback">الرابط جاهز للمشاركة</span>}
        <small>ملف PDF لقطة مختصرة وقت التصدير؛ الرابط يفتح التقرير الحالي.</small>
      </aside></div>
      {GUEST_MODE && <div className="customer-print-link">{qr && <img src={qr} alt="رمز تقرير الأسطوانة"/>}<div><strong dir="ltr">{report.serial}</strong><p>لقطة بيانات عرض · {date(report.generated_at, true)}</p><a href={publicUrl} dir="ltr">{publicUrl}</a></div></div>}
      <p className="customer-disclosure"><Info size={17}/>{report.disclosure}</p>
    </>}
  </div>;
}
