import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowLeft, ChevronLeft, ChevronRight, ClipboardList, FileText, Flame, History, Info, MapPin, RefreshCw, ScanLine, Search, TriangleAlert, Truck } from 'lucide-react';
import { api } from './api';
import Chart from './Chart';
import { CylinderShape } from './LpgSaddleDashboard';
import { DISPLAY_LOCALE } from './locale';
import { STATIONS, tripProgress, type ShipmentTrip } from './lpgMapData';
import { loadShipmentTrips } from './lpgTripSelection';
import './lpg-cylinders.css';

type Cylinder = { serial: string; position: number; current_saddle_id: string; current_trip_id: string };
type Place = { kind: 'station' | 'store'; trip_number: number };
type Journey = {
  id: string; trip_id: string; kind: 'delivery' | 'return' | 'transfer'; current: boolean;
  origin: Place; destination: Place; departed_at: string; arrived_at: string | null; expected_arrival_at: string; truck: string;
  membership: { cage_id: string; saddle_id: string; position: number; loaded_at: string; unloaded_at: string | null };
  scenario_number: number; reading_start_s: number; reading_end_s: number;
  arrival_inspection: { status: string; note: string; inspected_at: string } | null;
};
type Passport = Cylinder & { registered_at: string; nominal_fill_kg: number; journeys: Journey[] };
type Peak = { value: number; timestamp_s: number } | null;
type Evidence = {
  journey_id: string; expected_state: 'review' | 'unknown' | 'clear'; incomplete: boolean;
  coverage_percent: number; lpg_coverage_percent: number; sample_count: number; valid_sample_count: number;
  peaks: Record<string, Peak>; shock_events: number; lock_open_events: number; lock_open_observed_s: number;
  signals: Record<string, { max_score: number | null; confirmed: boolean; latest_state: string }>;
  alerts: { signal: string; title: string; timestamp_s: number; score: number }[];
  rows: any[]; window: { start_s: number; end_s: number };
};
const n = (value: number, digits = 1) => value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: digits });
const date = (iso: string, time = false) => new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', { timeZone: 'Asia/Riyadh', day: 'numeric', month: 'short', ...(time ? { hour: '2-digit', minute: '2-digit', hour12: false } : { year: 'numeric' }) }).format(new Date(iso));
const time = (iso: string) => new Intl.DateTimeFormat(DISPLAY_LOCALE, { timeZone: 'Asia/Riyadh', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso));
const kinds = { delivery: 'توزيع إلى متجر', return: 'إعادة إلى غازكو', transfer: 'انتقال بين مناطق التعبئة' };
const stateLabels = { clear: 'لا ملاحظة في القراءات المتاحة', review: 'يوصى بفحص عند الاستلام', unknown: 'الحالة غير محسومة' };
const signalNames: Record<string, string> = { mount_anomaly: 'انفعال التثبيت', thermal_anomaly: 'الحرارة', lpg_anomaly: 'مؤشر LPG' };
const channels = [['temperature', 'الحرارة'], ['gas', 'LPG'], ['strain', 'التثبيت A'], ['hoop', 'التثبيت B'], ['shock', 'الصدمات'], ['latch', 'القفل']];
const perPage = 18;

function observationNotes(e: Evidence): string[] {
  const notes: string[] = [];
  if (e.signals.lpg_anomaly.confirmed) notes.push('ظهرت إشارة LPG مؤكدة في منطقة القفص؛ يلزم فحص الأسطوانات والوصلات لتحديد المصدر.');
  else notes.push(e.signals.lpg_anomaly.latest_state === 'unknown' ? 'لا تكفي بيانات قناة LPG الأخيرة للحكم على وجود إشارة تسرب.' : 'لم تظهر إشارة LPG مؤكدة خلال الجزء المعروض من الرحلة.');
  if (e.signals.thermal_anomaly.confirmed) notes.push('رصد التحليل تغيرًا حراريًا؛ تُراجع ظروف التعرض للحرارة وموضع تركيب السراج.');
  if (e.signals.mount_anomaly.confirmed) notes.push('تغير انفعال عضو التثبيت؛ تُراجع سلامة تثبيت القفص عند الاستلام.');
  if (e.shock_events) notes.push(`سجلت ${n(e.shock_events, 0)} واقعة صدمة للقفص؛ أعلى تسارع ${n(e.peaks.shock!.value, 2)} g.`);
  if (e.lock_open_events) notes.push(`رصد فتح القفل ${n(e.lock_open_events, 0)} مرة، بإجمالي ${n(e.lock_open_observed_s, 0)} ثانية على ساعة القراءات.`);
  if (e.incomplete) notes.push(`تغطية القياسات ${n(e.coverage_percent)}%؛ الفجوات محفوظة ولا تُعامل كقراءات سليمة.`);
  if (!e.incomplete && !e.alerts.length && !e.shock_events && !e.lock_open_events) notes.push('القراءات المتاحة لا تتضمن ملاحظة حرارية أو ميكانيكية أو فتحًا للقفل يستدعي المراجعة.');
  return notes;
}

export default function LpgCylindersPage({ requestedSerial, contextTrip, onSelect, onSeraj }: {
  requestedSerial: string | null; contextTrip: ShipmentTrip | null;
  onSelect: (serial: string) => void; onSeraj: (trip: ShipmentTrip) => void;
}) {
  const [catalog, setCatalog] = useState<Cylinder[]>([]), [trips, setTrips] = useState<ShipmentTrip[]>([]);
  const [passport, setPassport] = useState<Passport | null>(null), [evidence, setEvidence] = useState<Record<string, Evidence>>({});
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [catalogError, setCatalogError] = useState('');
  const [retry, setRetry] = useState(0), [catalogRetry, setCatalogRetry] = useState(0), [selectedJourney, setSelectedJourney] = useState('');
  const [query, setQuery] = useState(''), [cage, setCage] = useState('all'), [listPage, setListPage] = useState(0);
  const [channel, setChannel] = useState('temperature'), [snapshotTime, setSnapshotTime] = useState(Date.now());
  const [snapshotProgress, setSnapshotProgress] = useState(0);
  const serial = requestedSerial || (() => { try { return sessionStorage.getItem('qaif.lpg.last-cylinder'); } catch { return null; } })() || 'CYL-001-01';

  useEffect(() => {
    let alive = true; setCatalogError('');
    Promise.all([api<{ cylinders: Cylinder[] }>('/lpg/demo/cylinders'), loadShipmentTrips()])
      .then(([data, routes]) => { if (alive) { setCatalog(data.cylinders); setTrips(routes); } })
      .catch(e => { if (alive) setCatalogError(e.message); });
    return () => { alive = false; };
  }, [catalogRetry]);
  useEffect(() => {
    if (!trips.length) return;
    let alive = true; setLoading(true); setError(''); setPassport(null); setEvidence({});
    api<Passport>(`/lpg/demo/cylinders/${encodeURIComponent(serial)}`).then(async record => {
      const current = record.journeys[record.journeys.length - 1];
      const template = trips.find(t => t.id === record.current_trip_id)!;
      const clockTrip = contextTrip?.id === template.id ? contextTrip : template;
      const progress = tripProgress({ ...clockTrip, initialProgress: clockTrip.viewProgress ?? clockTrip.initialProgress }, clockTrip.viewStartedMs ? Math.max(0, (snapshotTime - clockTrip.viewStartedMs) / 1000) : 0);
      const until = Math.floor(progress * 240) * 5;
      const values = await Promise.all(record.journeys.map(j => api<Evidence>(`/lpg/demo/cylinders/${encodeURIComponent(serial)}/journeys/${j.id}${j.current ? `?until_s=${until}` : ''}`)));
      if (!alive) return;
      setPassport(record); setSnapshotProgress(progress);
      setEvidence(Object.fromEntries(values.map(e => [e.journey_id, e])));
      setSelectedJourney(current.id); setLoading(false);
      try { sessionStorage.setItem('qaif.lpg.last-cylinder', serial); } catch { /* Selection remains in the URL. */ }
    }).catch(e => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [serial, trips, retry, snapshotTime]);

  const place = (p: Place) => {
    const trip = trips[p.trip_number - 1];
    const station = STATIONS.find(s => s.id === trip.stationId)!;
    return { name: p.kind === 'station' ? `غازكو · ${station.name}` : trip.destination.name, city: p.kind === 'station' ? station.name.replace('محطة ', '') : trip.destination.city, region: station.region };
  };
  const filtered = useMemo(() => catalog.filter(c => {
    const trip = trips.find(t => t.id === c.current_trip_id);
    const station = STATIONS.find(s => s.id === trip?.stationId);
    return (cage === 'all' || c.current_saddle_id === cage) && `${c.serial} ${c.current_saddle_id} ${trip?.destination.city || ''} ${station?.region || ''}`.toLowerCase().includes(query.trim().toLowerCase());
  }), [catalog, trips, query, cage]);
  useEffect(() => {
    const index = filtered.findIndex(c => c.serial === serial);
    setListPage(index < 0 ? 0 : Math.floor(index / perPage));
  }, [serial, filtered]);
  const current = passport?.journeys[passport.journeys.length - 1];
  const latest = current && evidence[current.id];
  const journey = passport?.journeys.find(j => j.id === selectedJourney);
  const selected = journey && evidence[journey.id];
  const journeyTime = (j: Journey, seconds: number) => new Date(new Date(j.departed_at).getTime() + Math.max(0, Math.min(1, (seconds - j.reading_start_s) / (j.reading_end_s - j.reading_start_s))) * (new Date(j.expected_arrival_at).getTime() - new Date(j.departed_at).getTime())).toISOString();
  const peakValue = (key: string, digits = 1) => selected?.peaks[key] ? n(selected.peaks[key]!.value, digits) : '—';
  const choose = (value: string) => { setSnapshotTime(Date.now()); setChannel('temperature'); onSelect(value); };

  return <div className="cylinder-page" data-testid="cylinder-page" data-cylinder-serial={serial}>
    {catalogError && <section className="panel cylinder-error" role="alert"><p>تعذر تحميل سجل الأسطوانات: {catalogError}</p><button onClick={() => setCatalogRetry(v => v + 1)}>إعادة المحاولة</button></section>}
    {loading && !catalogError ? <section className="panel cylinder-loading" role="status">جاري تجهيز هوية الأسطوانة وسجل رحلاتها…</section> : error ? <section className="panel cylinder-error" role="alert"><TriangleAlert size={20}/><p>تعذر فتح الأسطوانة: {error}</p><button onClick={() => setRetry(v => v + 1)}>إعادة المحاولة</button><button onClick={() => choose('CYL-001-01')}>فتح أول أسطوانة</button></section> : passport && latest && current && <>
      <section className="panel cylinder-passport">
        <div className="cylinder-passport-copy"><div className="cylinder-title-row"><div><p className="cylinder-id-caption"><ScanLine size={17}/>هوية أسطوانة ثابتة</p><h2 dir="ltr">{passport.serial}</h2></div><span className={`cylinder-state ${latest.expected_state}`}>{stateLabels[latest.expected_state]}</span></div>
          <p className="cylinder-state-explanation">{latest.expected_state === 'review' ? 'تعرضت منطقة القفص لملاحظة تستحق الفحص؛ لم يُثبت عطل فردي في هذه الأسطوانة.' : latest.expected_state === 'unknown' ? 'البيانات الحالية لا تكفي لتقدير حالة الأسطوانة أثناء النقل.' : 'تقدير مبني على قراءات القفص؛ يعتمد الحكم الفردي على فحص الأسطوانة.'}</p>
          <dl className="cylinder-identity-details"><div><dt>الموقع المتوقع</dt><dd>{snapshotProgress >= 1 ? `عند ${place(current.destination).name}` : `في الطريق إلى ${place(current.destination).city}`}</dd></div><div><dt>القفص الحالي · السراج</dt><dd dir="ltr">{current.membership.cage_id} · {current.membership.saddle_id}</dd></div><div><dt>حالة التداول</dt><dd>معبأة للتوزيع · {n(passport.nominal_fill_kg, 0)} كجم اسميًا</dd></div><div><dt>تاريخ بداية السجل</dt><dd>{date(passport.registered_at)}</dd></div></dl>
          <div className="cylinder-passport-actions"><a className="button-link" href={`#sources?serial=${passport.serial}`}><FileText size={16}/>تقرير العميل</a><button onClick={() => onSeraj(trips.find(t => t.id === passport.current_trip_id)!)}>تفاصيل السراج الحالي<ArrowLeft size={16}/></button><span>لقطة القراءات عند فتح السجل</span><button className="cylinder-refresh" onClick={() => setSnapshotTime(Date.now())} aria-label="تحديث لقطة قراءات الأسطوانة"><RefreshCw size={15}/></button></div>
        </div>
        <figure className="cylinder-portrait" aria-label={`أسطوانة برتقالية تحمل الرقم ${passport.serial}`}><CylinderShape/><figcaption dir="ltr">{passport.serial}</figcaption><span>هوية مستقلة عن القفص</span></figure>
        <dl className="cylinder-history-summary"><div><dt>عمليات نقل مسجلة</dt><dd>{n(passport.journeys.length, 0)}</dd></div><div><dt>أقفاص عبر تاريخها</dt><dd>{n(new Set(passport.journeys.map(j => j.membership.cage_id)).size, 0)}</dd></div><div><dt>مناطق مرّت بها</dt><dd>{n(new Set(passport.journeys.flatMap(j => [place(j.origin).region, place(j.destination).region])).size, 0)}</dd></div><div><dt>رقم الرحلة الحالية</dt><dd dir="ltr">{passport.current_trip_id}</dd></div></dl>
      </section>
    </>}

    <div className="cylinder-workspace">
      <div className="cylinder-detail-column">{passport && journey && selected && <>
        <section className="panel cylinder-journeys"><div className="cylinder-section-heading"><h3><History size={18}/>تاريخ الانتقال وسجل السفر</h3><span>اختر رحلة لعرض قراءاتها</span></div><ol>{[...passport.journeys].reverse().map(j => {
          const e = evidence[j.id], a = place(j.origin), b = place(j.destination);
          return <li key={j.id}><button className={`cylinder-journey-row ${j.id === selectedJourney ? 'selected' : ''}`} aria-pressed={j.id === selectedJourney} onClick={() => { setSelectedJourney(j.id); setChannel('temperature'); }} aria-label={`عرض رحلة ${j.trip_id}`}><span className={`cylinder-journey-dot ${e?.expected_state || 'unknown'}`}/><span className="cylinder-journey-date">{date(j.departed_at)}<small>{j.current ? snapshotProgress >= 1 ? 'وصلت في العرض' : 'قيد النقل في العرض' : 'مكتملة'}</small></span><span className="cylinder-journey-route"><strong>{a.name}<ChevronLeft size={13}/>{b.name}</strong><small>{a.region} ← {b.region} · {kinds[j.kind]}</small></span><span className="cylinder-journey-cage"><b dir="ltr">{j.membership.saddle_id}</b><small>{j.current ? stateLabels[e.expected_state] : e.expected_state === 'review' ? 'ملاحظة · فحص استلام مسجل' : e.expected_state === 'unknown' ? 'قياسات ناقصة · فحص مسجل' : 'استلام دون ملاحظة'}</small></span><ChevronLeft size={16}/></button></li>;
        })}</ol></section>

        <section className="panel cylinder-trip-detail" data-journey-id={journey.id} data-reading-end={selected.window.end_s}>
          <div className="cylinder-section-heading"><h3><Truck size={18}/>تفاصيل رحلة الأسطوانة</h3><span dir="ltr">{journey.trip_id}</span></div>
          <div className="cylinder-selected-route"><div><MapPin size={18}/><span><small>من</small><strong>{place(journey.origin).name}</strong><em>{place(journey.origin).region}</em></span></div><ChevronLeft size={23}/><div><MapPin size={18}/><span><small>إلى</small><strong>{place(journey.destination).name}</strong><em>{place(journey.destination).region}</em></span></div></div>
          <dl className="cylinder-trip-facts"><div><dt>الانطلاق</dt><dd>{date(journey.departed_at, true)}</dd></div><div><dt>{journey.current ? 'الوصول المتوقع في السيناريو' : 'الوصول'}</dt><dd>{date(journey.arrived_at || journey.expected_arrival_at, true)}</dd></div><div><dt>الشاحنة</dt><dd dir="ltr">{journey.truck}</dd></div><div><dt>القفص · موضع الأسطوانة</dt><dd><b dir="ltr">{journey.membership.cage_id}</b> · {n(journey.membership.position, 0)}</dd></div><div><dt>بداية وجودها في القفص</dt><dd>{date(journey.membership.loaded_at, true)}</dd></div><div><dt>نهاية وجودها في القفص</dt><dd>{journey.membership.unloaded_at ? date(journey.membership.unloaded_at, true) : 'ما زالت مرتبطة بهذا القفص'}</dd></div></dl>
          <div className="cylinder-evidence-heading"><h4>قراءات السراج أثناء وجود الأسطوانة</h4><span>السراج <b dir="ltr">{journey.membership.saddle_id}</b> · تغطية <b dir="ltr">{n(selected.coverage_percent)}%</b></span></div>
          <p className="cylinder-shared-note">هذه قياسات مشتركة لمنطقة القفص، وترتبط بالأسطوانة خلال فترة عضويتها في الرحلة.</p>
          <dl className="cylinder-peak-grid">{[
            ['temperature', 'أعلى حرارة', '°C', 1], ['lpg', 'أعلى قراءة LPG', 'ppm', 4], ['strain_a', 'أقصى انفعال A', 'µε', 1], ['strain_b', 'أقصى انفعال B', 'µε', 1], ['shock', 'أعلى تسارع', 'g', 2],
          ].map(([key, label, unit, digits]) => <div key={key as string}><dt>{label}</dt><dd dir="ltr">{peakValue(key as string, digits as number)} <small>{unit}</small></dd><span>{selected.peaks[key as string] ? `عند ${time(journeyTime(journey, selected.peaks[key as string]!.timestamp_s))}` : 'لا قراءة متاحة'}</span></div>)}<div><dt>فتح القفل</dt><dd>{n(selected.lock_open_events, 0)} <small>مرة</small></dd><span>{n(selected.lock_open_observed_s, 0)} ثانية مرصودة</span></div></dl>
          <div className="cylinder-leak-indicator"><Flame size={20}/><div><strong>مؤشر التسرب في منطقة القفص</strong><span>{selected.signals.lpg_anomaly.confirmed ? 'إشارة LPG مؤكدة · يلزم تحديد المصدر بالفحص' : selected.signals.lpg_anomaly.latest_state === 'unknown' ? 'غير محسوم بسبب نقص القياسات' : 'لا إشارة LPG مؤكدة في الفترة المعروضة'}</span></div><span className={`cylinder-state ${selected.signals.lpg_anomaly.confirmed ? 'review' : selected.signals.lpg_anomaly.latest_state === 'unknown' ? 'unknown' : 'clear'}`}>{selected.signals.lpg_anomaly.max_score == null ? '—' : <><b dir="ltr">{n(selected.signals.lpg_anomaly.max_score, 3)}</b><small>أعلى درجة</small></>}</span></div>
          <div className="cylinder-notes"><h4><ClipboardList size={17}/>ملخص ملاحظات الرحلة</h4><ul>{observationNotes(selected).map(note => <li key={note}>{note}</li>)}</ul>{journey.arrival_inspection && <p className="cylinder-inspection"><strong>فحص الاستلام · {date(journey.arrival_inspection.inspected_at, true)}</strong>{journey.arrival_inspection.note}</p>}</div>
          <details className="cylinder-technical" open><summary><Activity size={16}/>القراءات وتحليل السراج بالتفصيل</summary><div className="cylinder-chart-tabs" role="group" aria-label="قناة سجل رحلة الأسطوانة">{channels.map(([id, label]) => <button key={id} className={channel === id ? 'active' : ''} aria-pressed={channel === id} onClick={() => setChannel(id)}>{label}</button>)}</div>{selected.rows.length ? <Chart episode={{ rows: selected.rows, simulation_clock: false }} channel={channel} profile="shipment"/> : <p>لا توجد قياسات داخل فترة العضوية حتى هذه اللقطة.</p>}
            <div className="cylinder-table-wrap"><table className="cylinder-signal-table"><caption>أعلى درجات التحليل داخل فترة العضوية</caption><thead><tr><th scope="col">القناة</th><th scope="col">أعلى درجة</th><th scope="col">إشارة مؤكدة</th></tr></thead><tbody>{Object.entries(selected.signals).map(([key, signal]) => <tr key={key}><th scope="row">{signalNames[key]}</th><td dir="ltr">{signal.max_score == null ? '—' : n(signal.max_score, 3)}</td><td>{signal.confirmed ? 'نعم · 3 قراءات متتالية' : signal.latest_state === 'unknown' ? 'البيانات غير مكتملة' : 'لم تسجل'}</td></tr>)}</tbody></table></div>
            {selected.alerts.length > 0 && <ul className="cylinder-alert-list">{selected.alerts.map(a => <li key={a.signal}><TriangleAlert size={15}/><span>{a.title}</span><time>{time(journeyTime(journey, a.timestamp_s))}</time><b dir="ltr">{n(a.score, 3)}</b></li>)}</ul>}
            <p className="cylinder-technical-note">{n(selected.valid_sample_count, 0)} / {n(selected.sample_count, 0)} عينة صالحة · تغطية قناة LPG {n(selected.lpg_coverage_percent)}% · كل 5 ثوانٍ على ساعة المحاكي. درجات النموذج ليست احتمالات تسرب معايرة.</p>
          </details>
        </section>
      </>}</div>

      <aside className="panel cylinder-registry" aria-label="سجل جميع الأسطوانات"><div className="cylinder-section-heading"><h3><ScanLine size={18}/>سجل الأسطوانات</h3><span>{n(catalog.length, 0)} أسطوانة</span></div><label className="cylinder-search"><Search size={16}/><input aria-label="البحث عن أسطوانة" placeholder="رقم تسلسلي أو مدينة" value={query} onChange={e => setQuery(e.target.value)}/></label><label className="cylinder-filter"><span>القفص الحالي</span><select aria-label="تصفية الأسطوانات حسب السراج" value={cage} onChange={e => setCage(e.target.value)}><option value="all">جميع الأقفاص</option>{trips.map(t => <option value={t.saddleId} key={t.id}>{t.saddleId} · {t.destination.city}</option>)}</select></label><p className="cylinder-result-count">{n(filtered.length, 0)} نتيجة · لكل هوية سجل مستقل</p><div className="cylinder-registry-list">{filtered.slice(listPage * perPage, (listPage + 1) * perPage).map(c => <button key={c.serial} className={c.serial === serial ? 'selected' : ''} aria-current={c.serial === serial ? 'true' : undefined} onClick={() => choose(c.serial)} aria-label={`اختيار الأسطوانة ${c.serial}`}><CylinderShape/><span><strong dir="ltr">{c.serial}</strong><small>{trips.find(t => t.id === c.current_trip_id)?.destination.city} · <b dir="ltr">{c.current_saddle_id}</b></small></span><ChevronLeft size={14}/></button>)}</div>{!filtered.length && <div className="cylinder-empty"><p>لا توجد أسطوانة تطابق البحث.</p><button onClick={() => { setQuery(''); setCage('all'); }}>مسح البحث والتصفية</button></div>}{filtered.length > perPage && <div className="cylinder-pagination"><button disabled={listPage === 0} onClick={() => setListPage(v => v - 1)} aria-label="الصفحة السابقة من الأسطوانات"><ChevronRight size={17}/></button><span dir="ltr">{n(listPage + 1, 0)} / {n(Math.ceil(filtered.length / perPage), 0)}</span><button disabled={(listPage + 1) * perPage >= filtered.length} onClick={() => setListPage(v => v + 1)} aria-label="الصفحة التالية من الأسطوانات"><ChevronLeft size={17}/></button></div>}</aside>
    </div>
    <details className="cylinder-provenance"><summary><Info size={16}/>مصدر السجل والقراءات</summary><p>سجل عرض ثابت لـ189 هوية، مع تواريخ انتقال وعضوية أقفاص وفحوص استلام توضيحية. الرحلات السابقة تعيد استخدام سيناريوهات قراءات السراج، والرحلة الحالية تعرض القراءات المتاحة حتى اللقطة فقط. أعلى القراءات والملخصات محسوبة من بيانات المحاكي داخل فترة وجود الأسطوانة. قناة H₂S ممثلة باسم LPG، والتحليل بالنموذج السابق 416؛ لم يُدرّب بعد على LPG. هذه البيانات لا تمثل سجلًا تشغيليًا ميدانيًا، ولا تعني ملاحظات القفص إثبات عطل أسطوانة فردية.</p></details>
  </div>;
}
