import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, ArrowLeft, ChevronLeft, ClipboardList, Flame, Gauge, Info, LockKeyhole, Pause, Play, Radio, ScanLine, Thermometer, TriangleAlert, Truck, Vibrate } from 'lucide-react';
import { api } from './api';
import Chart from './Chart';
import LpgTripMiniMap from './LpgTripMiniMap';
import { STATIONS, tripProgress, type ShipmentTrip } from './lpgMapData';
import { DISPLAY_LOCALE } from './locale';
import './lpg-saddle.css';

type Reading = { timestamp_s: number; packet_valid: boolean; mount_strain_a: number | null; mount_strain_b: number | null; mount_temperature_C: number | null; lpg_ppm: number | null; lpg_valid: boolean; acceleration_g: number; latch_closed: boolean };
type Signal = { state: 'unknown' | 'present' | 'absent'; score: number | null; alarm: boolean | null };
type Prediction = { timestamp_s: number; quality: string; signals: Record<string, Signal> };
type Demo = { rows: Reading[]; inference_history: Prediction[]; alerts: { signal: string; title: string; timestamp_s: number; score: number }[]; cylinders: { serial: string; position: number }[]; model_version: string; source: string };
const n = (value: number, decimals = 1) => value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: decimals });
const clock = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const channels = [ ['strain', 'التثبيت A'], ['hoop', 'التثبيت B'], ['temperature', 'الحرارة'], ['gas', 'LPG'], ['shock', 'الصدمات'], ['latch', 'القفل'] ];
const heads = [ ['mount_anomaly', 'انفعال التثبيت'], ['thermal_anomaly', 'الحرارة'], ['lpg_anomaly', 'LPG'] ];

export function CylinderShape() {
  return <svg className="shipment-cylinder-shape" viewBox="0 0 72 104" aria-hidden="true">
    <path d="M23 19V8h26v11M29 8V5h14v3" fill="none" stroke="currentColor" strokeWidth="3" strokeLinejoin="round"/>
    <path d="M31 18v-5h10v5" fill="#6772e8"/>
    <path d="M26 21C16 24 12 31 12 42v39c0 8 5 13 12 13h24c7 0 12-5 12-13V42c0-11-4-18-14-21Z" fill="#fa965a" stroke="#ae5926" strokeWidth="1.5"/>
    <path d="M18 43v37c0 5 2 7 5 8" fill="none" stroke="#ffc39d" strokeWidth="3" strokeLinecap="round"/>
    <path d="M12 46h48M12 79h48" stroke="#cf763b" strokeWidth="1.5"/>
    <rect x="26" y="52" width="20" height="17" rx="3" fill="#fff5ee"/>
    <path d="M36 55c-4 4-5 5-5 8a5 5 0 0 0 10 0c0-2-1-4-3-6v5c-2-2-2-4-2-7Z" fill="#c16d37"/>
    <path d="M22 94v5h28v-5" fill="none" stroke="#ae5926" strokeWidth="3" strokeLinejoin="round"/>
  </svg>;
}

export default function LpgSaddleDashboard({ trip, onBack, onCylinder, onInspection }: { trip: ShipmentTrip; onBack: () => void; onCylinder: (serial: string, progress: number) => void; onInspection?: (progress: number) => void }) {
  const [data, setData] = useState<Demo | null>(null), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const [channel, setChannel] = useState('strain'), [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(() => Math.max(0, (Date.now() - (trip.viewStartedMs ?? Date.now())) / 1000));
  const elapsedRef = useRef(elapsed);
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const station = STATIONS.find(s => s.id === trip.stationId)!;
  const progress = tripProgress({ ...trip, initialProgress: trip.viewProgress ?? trip.initialProgress }, elapsed);
  useEffect(() => {
    let alive = true; setError(''); setData(null);
    api<Demo>(`/lpg/demo/seraj/${Number(trip.saddleId.replace('S-', ''))}`)
      .then(value => { if (alive) setData(value); })
      .catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [trip.id, retry]);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(media.matches); media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (paused || progress >= 1) return;
    let previous = performance.now();
    const timer = setInterval(() => {
      const time = performance.now(); elapsedRef.current += (time - previous) / 1000; previous = time;
      setElapsed(elapsedRef.current);
    }, reduced ? 1000 : 250);
    return () => clearInterval(timer);
  }, [paused, reduced, progress >= 1]);
  const sampleIndex = data ? Math.min(data.rows.length - 1, Math.floor(progress * (data.rows.length - 1))) : 0;
  const episode = useMemo(() => data ? { rows: data.rows.slice(0, sampleIndex + 1), simulation_clock: true } : null, [data, sampleIndex]);
  const current = data?.rows[sampleIndex], ai = data?.inference_history[sampleIndex];
  const valid = current?.packet_valid === true;
  const alerts = data?.alerts.filter(a => a.timestamp_s <= (current?.timestamp_s ?? 0)) ?? [];
  const coverage = episode ? episode.rows.filter(row => row.packet_valid).length / episode.rows.length * 100 : 0;
  const partial = valid && heads.some(([key]) => ai?.signals[key]?.state === 'unknown');
  const status = !data ? 'loading' : !valid || partial || ai?.quality === 'insufficient' ? 'unknown' : alerts.length ? 'alert' : 'healthy';
  const statusLabel = { loading: 'جاري تجهيز القراءات', unknown: 'المراقبة غير مكتملة', alert: 'يحتاج فحصًا عند الوصول', healthy: 'لا تنبيه في القراءات الحالية' }[status];
  const readingValue = (value: number | null | undefined, decimals = 1) => valid && typeof value === 'number' ? n(value, decimals) : '—';
  const metrics = [
    { key: 'strain', icon: Gauge, label: 'انفعال التثبيت A', value: readingValue(current?.mount_strain_a), unit: 'µε', hint: 'عضو التثبيت · اتجاه A', tone: 'indigo' },
    { key: 'hoop', icon: Activity, label: 'انفعال التثبيت B', value: readingValue(current?.mount_strain_b), unit: 'µε', hint: 'عضو التثبيت · اتجاه B', tone: 'purple' },
    { key: 'temperature', icon: Thermometer, label: 'حرارة موضع السراج', value: readingValue(current?.mount_temperature_C), unit: '°C', hint: 'حرارة المعدن عند الرقعة', tone: 'rose' },
    { key: 'gas', icon: Flame, label: 'قناة LPG', value: current?.lpg_valid ? readingValue(current.lpg_ppm, 3) : '—', unit: 'ppm', hint: 'قراءة منطقة القفص', tone: 'orange' },
    { key: 'shock', icon: Vibrate, label: 'تسارع القفص', value: valid ? n(current!.acceleration_g, 2) : '—', unit: 'g', hint: 'الصدمات والاهتزاز', tone: 'purple' },
    { key: 'latch', icon: LockKeyhole, label: 'حالة القفل', value: valid ? current?.latch_closed ? 'مغلق' : 'مفتوح' : '—', unit: '', hint: 'حالة الفتح والإغلاق', tone: 'indigo' },
  ];
  return <div className="shipment-dashboard" data-testid="shipment-dashboard" data-trip-id={trip.id} data-sample={sampleIndex} data-progress={progress}>
    <section className="panel shipment-header">
      <div className="shipment-header-top"><div className="shipment-identity"><span className="shipment-truck-icon"><Truck size={26}/></span><div><h2>سراج الشحنة <b dir="ltr">{trip.saddleId}</b></h2><p><b dir="ltr">{trip.truck}</b><span>·</span><b dir="ltr">{trip.id}</b></p></div></div><button onClick={onBack}>العودة للخريطة<ArrowLeft size={17}/></button></div>
      <div className="shipment-header-bottom"><div className="shipment-route"><strong>{station.name}</strong><ChevronLeft size={17}/><strong>{trip.destination.city}</strong></div><span className={`shipment-status ${status}`}><i/>{statusLabel}</span></div>
    </section>
    {error ? <section className="panel shipment-error" role="alert"><TriangleAlert size={20}/><p>تعذر تحميل قراءات السراج: {error}</p><button onClick={() => setRetry(v => v + 1)}>إعادة المحاولة</button></section> : !data ? <div className="panel shipment-loading" role="status">جاري تجهيز القراءات وتحليلها…</div> : <>
      <div className="shipment-reading-heading"><div><h3>قراءات السراج</h3><span><Radio size={14}/>{valid ? partial ? 'القياسات جزئية' : 'القياسات متاحة' : 'توقف وصول القياسات'} · التغطية <b dir="ltr">{n(coverage, 0)}%</b></span></div><div><span>زمن القراءات <b dir="ltr">{clock(current!.timestamp_s)}</b></span><button onClick={() => setPaused(v => !v)} disabled={progress >= 1} aria-label={paused ? 'استئناف عرض الشحنة' : 'إيقاف عرض الشحنة'}>{paused ? <Play size={15}/> : <Pause size={15}/>} {progress >= 1 ? 'اكتملت الرحلة' : paused ? 'استئناف' : 'إيقاف العرض'}</button></div></div>
      <div className="shipment-metrics" aria-label="آخر قراءات سراج الشحنة">{metrics.map(metric => <button key={metric.key} className={`shipment-metric ${metric.tone} ${channel === metric.key ? 'selected' : ''}`} onClick={() => setChannel(metric.key)} aria-pressed={channel === metric.key} aria-label={`عرض رسم ${metric.label}`}><span className="shipment-metric-name"><metric.icon size={18}/>{metric.label}</span><strong dir="ltr">{metric.value}<small>{metric.unit}</small></strong><span className="shipment-metric-hint">{valid ? metric.hint : 'القراءة الحالية غير متاحة'}</span></button>)}</div>
      <div className="shipment-columns">
        <div className="shipment-main-column">
          <section className="panel shipment-chart-panel"><div className="panel-heading"><h3><Activity size={18}/>سجل القراءات</h3><span>كل <b dir="ltr">5</b> ثوانٍ</span></div><div className="shipment-channel-tabs" role="group" aria-label="اختيار قناة الرسم">{channels.map(([id, label]) => <button key={id} onClick={() => setChannel(id)} aria-pressed={channel === id} className={channel === id ? 'active' : ''}>{label}</button>)}</div><Chart episode={episode} channel={channel} profile="shipment"/></section>
          <section className="panel shipment-ai-panel"><div className="panel-heading"><h3><Activity size={18}/>تحليل القراءات</h3><span className="shipment-model-tag" dir="ltr">XGBoost · 416</span></div><div className="shipment-ai-table-wrap"><table className="shipment-ai-table"><thead><tr><th scope="col">القناة</th><th scope="col">نتيجة التحليل</th><th scope="col">درجة النموذج</th></tr></thead><tbody>{heads.map(([key, label]) => {
            const signal = ai?.signals[key];
            const state = signal?.state ?? 'unknown';
            return <tr key={key}><th scope="row">{label}</th><td><span className={`shipment-signal ${state}`}><i/>{state === 'unknown' ? 'غير متاح' : signal?.alarm ? 'إشارة مؤكدة' : state === 'present' ? 'بانتظار التأكيد' : 'لا تظهر إشارة'}</span></td><td dir="ltr">{signal?.score != null ? n(signal.score, 3) : '—'}</td></tr>;
          })}</tbody></table></div><p className="shipment-ai-note">الدرجة ليست احتمالًا معايرًا. الصدمات وحالة القفل معروضة كقنوات مستقلة عن النموذج.</p></section>
          <section className="panel shipment-observations"><div className="panel-heading"><h3><TriangleAlert size={18}/>ملاحظات الرحلة</h3><span>{n(alerts.length, 0)} إشارات</span></div>{alerts.length ? <ul>{alerts.map(alert => <li key={alert.signal}><TriangleAlert size={17}/><div><strong>{alert.title}</strong><p>ظهرت إشارة بعد تأكيدها في <b dir="ltr">3</b> قراءات متتالية؛ تُراجع منطقة القفص عند الوصول.</p></div><time dir="ltr">{clock(alert.timestamp_s)}</time></li>)}</ul> : <p className="shipment-empty-note">{valid ? 'لم يسجل التحليل إشارة تستدعي الفحص حتى هذه القراءة.' : 'توجد فجوة في القياسات؛ لا تكفي البيانات الحالية للحكم على حالة الشحنة.'}</p>}{!valid && alerts.length > 0 && <p className="shipment-empty-note">القياسات الحالية غير متاحة؛ الإشارات السابقة محفوظة في عرض الرحلة.</p>}</section>
        </div>
        <aside className="shipment-side-column">
          <LpgTripMiniMap trip={trip} progress={progress}/>
          <section className="panel shipment-cylinders-panel"><div className="panel-heading"><h3><ScanLine size={18}/>أسطوانات القفص</h3><span><b dir="ltr">9</b> أسطوانات</span></div><p className="shipment-cylinders-caption">اضغط على الأسطوانة لفتح نافذتها.</p><div className="shipment-cylinder-grid" aria-label="الأسطوانات التسع في قفص سراج الشحنة">{data.cylinders.map(cylinder => <button key={cylinder.serial} className="shipment-cylinder" onClick={() => onCylinder(cylinder.serial, progress)} aria-label={`فتح الأسطوانة ${cylinder.serial}`}><CylinderShape/><strong dir="ltr">{cylinder.serial}</strong><span>داخل القفص</span></button>)}</div><p className="shipment-cylinders-footnote">ملاحظات السراج تخص منطقة القفص؛ الفحص الفردي يحدد حالة كل أسطوانة.</p></section>
        </aside>
      </div>
    </>}
    {onInspection && <section className="panel shipment-inspection-link"><p>طلب فحص مرتبط بسراج الشحنة ولقطة قراءات الرحلة.</p><button onClick={() => onInspection(progress)}><ClipboardList size={16}/>طلب فحص السراج</button></section>}
    <details className="shipment-provenance"><summary><Info size={15}/>مصدر بيانات العرض والتحليل</summary><p>قراءات مشتقة من محاكي الأنابيب مع بيانات عرض للصدمات والقفل وهوية الأسطوانات. قناة H₂S السابقة ممثلة هنا باسم LPG. نتائج التحليل محسوبة بالنموذج السابق <b dir="ltr">416</b> عبر ربط تجريبي؛ لم يُدرّب أو يُختبر بعد لشحنات LPG. حركة الرحلة عرض مختصر.</p></details>
  </div>;
}
