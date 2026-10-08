import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowLeft, CheckSquare, ChevronLeft, ClipboardList, Clock, History, Info, Plus, Search, ShieldCheck, Truck, UserRound } from 'lucide-react';
import { api } from './api';
import { DISPLAY_LOCALE } from './locale';
import { STATIONS, tripProgress, type ShipmentTrip } from './lpgMapData';
import { loadShipmentTrips } from './lpgTripSelection';
import './lpg-inspections.css';

type TaskStatus = 'new' | 'in_progress' | 'review' | 'closed' | 'cancelled';
type Condition = 'pending' | 'normal' | 'maintenance' | 'isolate' | 'undetermined';
type Assessment = { condition: Condition; findings: string; recommendation: string; gas_check: string; mount_check: string; latch_check: string; at: string; by: string; source: string };
type Task = { id: string; number: number; saddle_id: string; trip_id: string; status: TaskStatus; condition: Condition; priority: 'urgent' | 'high' | 'normal'; reason: string; scheduled_at: string; created_at: string; updated_at: string; requested_by: string; assignee: string; assessment: Assessment | null; decision: string; evidence_until_s: number; history: { status: TaskStatus; at: string; actor: string; note: string }[] };
type Evidence = { expected_state: 'review' | 'unknown' | 'clear'; incomplete: boolean; coverage_percent: number; peaks: Record<string, { value: number; timestamp_s: number } | null>; alerts: { title: string; signal: string; timestamp_s: number; score: number }[]; signals: Record<string, { confirmed: boolean; max_score: number | null; latest_state: string }>; shock_events: number; lock_open_events: number };
const statuses: Record<TaskStatus, string> = { new: 'طلب جديد', in_progress: 'قيد الفحص', review: 'بانتظار اعتماد القرار', closed: 'مغلقة', cancelled: 'ملغاة' };
const conditions: Record<Condition, string> = { pending: 'بانتظار تقييم المفتش', normal: 'لم يسجل الفحص ملاحظة', maintenance: 'يحتاج صيانة', isolate: 'يوصى بعزل القفص', undetermined: 'الحالة غير محسومة' };
const priorities = { urgent: 'عاجلة', high: 'مرتفعة', normal: 'عادية' };
const gasChecks: Record<string, string> = { not_checked: 'لم يفحص', no_indication: 'لا إشارة أثناء الفحص', indication: 'رصدت إشارة تستدعي التحقق', inconclusive: 'نتيجة غير حاسمة' };
const mountChecks: Record<string, string> = { not_checked: 'لم يفحص', normal: 'دون ملاحظة ظاهرة', loose: 'تثبيت مرتخٍ', damaged: 'تلف ظاهر' };
const latchChecks: Record<string, string> = { not_checked: 'لم يفحص', normal: 'القفل يعمل دون ملاحظة', damaged: 'خلل في القفل' };
const heads: Record<string, string> = { lpg_anomaly: 'قناة LPG', thermal_anomaly: 'الحرارة', mount_anomaly: 'انفعال التثبيت' };
const n = (value: number, digits = 1) => value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: digits });
const date = (iso: string) => iso ? new Intl.DateTimeFormat('ar-SA-u-ca-gregory-nu-latn', { timeZone: 'Asia/Riyadh', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso)) : 'لم يحدد';
const tripNumber = (id: string | null | undefined) => { const value = Number(id?.split('-')[1]); return Number.isInteger(value) && value >= 1 && value <= 21 ? value : 1; };
const active = (task: Task) => !['closed', 'cancelled'].includes(task.status);

export default function LpgInspectionsPage({ requestedTask, requestedTrip, requestNew, contextTrip, canRequest, canEvaluate, onSelect, onSeraj, onChanged }: {
  requestedTask: string | null; requestedTrip: string | null; requestNew: boolean; contextTrip: ShipmentTrip | null;
  canRequest: boolean; canEvaluate: boolean; onSelect: (id: string) => void; onSeraj: (trip: ShipmentTrip) => void; onChanged: () => Promise<void>;
}) {
  const [tasks, setTasks] = useState<Task[]>([]), [trips, setTrips] = useState<ShipmentTrip[]>([]);
  const [loading, setLoading] = useState(true), [loadError, setLoadError] = useState(''), [retry, setRetry] = useState(0);
  const [evidence, setEvidence] = useState<Evidence | null>(null), [evidenceError, setEvidenceError] = useState('');
  const [query, setQuery] = useState(''), [filter, setFilter] = useState('open');
  const [newOpen, setNewOpen] = useState(requestNew), [draftNumber, setDraftNumber] = useState(tripNumber(requestedTrip || contextTrip?.id));
  const [action, setAction] = useState<'assign' | 'result' | 'close' | 'cancel' | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => {
    let alive = true; setLoading(true); setLoadError('');
    Promise.all([api<Task[]>('/lpg/inspections'), loadShipmentTrips()]).then(([items, routes]) => {
      if (alive) { setTasks(items); setTrips(routes); setLoading(false); }
    }).catch(e => { if (alive) { setLoadError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [retry]);
  useEffect(() => {
    setNewOpen(requestNew); setAction(null); setError('');
    if (requestedTrip) setDraftNumber(tripNumber(requestedTrip));
  }, [requestNew, requestedTrip]);
  const task = tasks.find(t => t.id === requestedTask) || (!requestedTask ? tasks[0] : null);
  const trip = trips.find(t => t.id === task?.trip_id);
  const station = STATIONS.find(s => s.id === trip?.stationId);
  const existing = tasks.find(t => t.number === draftNumber && active(t));
  useEffect(() => {
    setAction(null); setError(''); setEvidence(null); setEvidenceError('');
    if (!task) return;
    let alive = true;
    api<Evidence>(`/lpg/inspections/${task.id}/evidence`).then(value => { if (alive) setEvidence(value); }).catch(e => { if (alive) setEvidenceError(e.message); });
    return () => { alive = false; };
  }, [task?.id, task?.updated_at, retry]);
  useEffect(() => { if (requestedTask && task && !active(task)) setFilter('all'); }, [requestedTask, task?.id, task?.status]);
  const visible = useMemo(() => tasks.filter(t => {
    const route = trips.find(r => r.id === t.trip_id);
    return (filter === 'all' || (filter === 'open' ? active(t) : t.status === filter)) && `${t.saddle_id} ${t.trip_id} ${t.id} ${t.reason} ${route?.destination.city || ''}`.toLowerCase().includes(query.trim().toLowerCase());
  }), [tasks, trips, query, filter]);
  const refresh = async () => { setTasks(await api<Task[]>('/lpg/inspections')); await onChanged(); };
  const save = async (work: () => Promise<Task>, message: string) => {
    setBusy(true); setError(''); setNotice('');
    try { const updated = await work(); await refresh(); setAction(null); setNewOpen(false); onSelect(updated.id); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : 'تعذر حفظ المهمة'); }
    finally { setBusy(false); }
  };
  const submitNew = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget));
    const route = trips.find(t => Number(t.saddleId.slice(2)) === draftNumber)!;
    const clockTrip = contextTrip?.id === route.id ? contextTrip : route;
    const progress = tripProgress({ ...clockTrip, initialProgress: clockTrip.viewProgress ?? clockTrip.initialProgress }, clockTrip.viewStartedMs ? Math.max(0, (Date.now() - clockTrip.viewStartedMs) / 1000) : 0);
    save(() => api<Task>('/lpg/inspections', { number: draftNumber, reason: values.reason, priority: values.priority, scheduled_at: values.scheduled_at ? `${values.scheduled_at}:00+03:00` : '', evidence_until_s: Math.floor(progress * 240) * 5 }), 'تم حفظ طلب فحص سراج الشحنة.');
  };
  const submitAction = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!task) return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const target = action === 'assign' ? 'in_progress' : action === 'result' ? 'review' : action === 'close' ? 'closed' : 'cancelled';
    save(() => api<Task>(`/lpg/inspections/${task.id}/transition`, { ...values, status: target }), action === 'result' ? 'تم حفظ التقييم؛ بانتظار اعتماد القرار.' : action === 'close' ? 'تم حفظ قرار الإغلاق.' : action === 'cancel' ? 'تم حفظ إلغاء الطلب.' : 'تم تعيين المفتش وبدء المهمة.');
  };
  const startAction = (next: typeof action) => { setAction(next); setNewOpen(false); setError(''); setNotice(''); };

  if (loading) return <section className="panel" role="status">جاري تجهيز مهام فحص سروج الشحنات…</section>;
  if (loadError) return <section className="panel lpg-inspection-error" role="alert"><p>{loadError}</p><button onClick={() => setRetry(v => v + 1)}>إعادة المحاولة</button></section>;
  return <div className="lpg-inspection-page" data-testid="lpg-inspection-page" data-task-id={task?.id || ''}>
    <div className="lpg-inspection-toolbar"><p><Truck size={17}/>مهام سراج الشحنة والقفص</p>{canRequest && <button className="primary" disabled={busy} onClick={() => { setNewOpen(true); setAction(null); setError(''); setNotice(''); }}><Plus size={17}/>طلب فحص سراج</button>}</div>
    <dl className="lpg-inspection-counts">{[
      ['طلبات جديدة', tasks.filter(t => t.status === 'new').length, ClipboardList], ['قيد الفحص', tasks.filter(t => t.status === 'in_progress').length, Clock], ['بانتظار القرار', tasks.filter(t => t.status === 'review').length, ShieldCheck], ['مغلقة', tasks.filter(t => t.status === 'closed').length, CheckSquare],
    ].map(([label, count, Icon]) => { const Symbol = Icon as typeof Clock; return <div key={label as string}><Symbol size={19}/><dt>{label as string}</dt><dd dir="ltr">{n(count as number, 0)}</dd></div>; })}</dl>
    {notice && <p className="lpg-inspection-notice" role="status">{notice}</p>}
    {error && <p className="lpg-inspection-error" role="alert">{error}</p>}
    {newOpen && canRequest && <section className="panel lpg-inspection-form-panel"><div className="lpg-inspection-heading"><h2>طلب فحص سراج الشحنة</h2><button disabled={busy} onClick={() => setNewOpen(false)}>إغلاق النموذج</button></div><form onSubmit={submitNew}><div className="lpg-inspection-form-grid"><label>سراج الشحنة<select aria-label="سراج الشحنة المطلوب فحصه" value={draftNumber} onChange={e => setDraftNumber(Number(e.target.value))}>{trips.map(t => <option key={t.id} value={Number(t.saddleId.slice(2))}>{t.saddleId} · {t.destination.city}</option>)}</select></label><label>الأولوية<select name="priority" defaultValue="normal"><option value="normal">عادية</option><option value="high">مرتفعة</option><option value="urgent">عاجلة</option></select></label><label>موعد الفحص · توقيت الرياض<input name="scheduled_at" type="datetime-local"/></label></div><label>سبب طلب الفحص<textarea name="reason" required minLength={3} maxLength={2000} placeholder="الملاحظة المطلوب التحقق منها في السراج أو القفص"/></label>{existing && <p className="lpg-inspection-existing">يوجد طلب مفتوح لهذا السراج في الرحلة الحالية.<button type="button" onClick={() => { setNewOpen(false); onSelect(existing.id); }}>فتح المهمة الحالية<ChevronLeft size={14}/></button></p>}<p className="lpg-inspection-note">تُحفظ لقطة قراءات الرحلة مع الطلب لتقييم سبب الفحص.</p><button className="primary" type="submit" disabled={busy || !!existing}>{busy ? 'جاري الحفظ…' : 'حفظ طلب الفحص'}</button></form></section>}

    <div className="lpg-inspection-workspace"><div className="lpg-inspection-detail">{requestedTask && !task ? <section className="panel" role="alert">مهمة فحص الشحنة المطلوبة غير موجودة. اختر مهمة من القائمة.</section> : task && trip && station ? <>
      <section className="panel lpg-inspection-identity"><div className="lpg-inspection-heading"><div><h2>سراج الشحنة <b dir="ltr">{task.saddle_id}</b></h2><p dir="ltr">{task.id} · {task.trip_id}</p></div><span className={`lpg-task-status ${task.status}`}>{statuses[task.status]}</span></div><div className="lpg-inspection-route"><strong>{station.name}</strong><ChevronLeft size={15}/><strong>{trip.destination.name}</strong><span className={`lpg-task-priority ${task.priority}`}>أولوية {priorities[task.priority]}</span></div><p className="lpg-inspection-reason">{task.reason}</p><dl className="lpg-inspection-facts"><div><dt>طالب الفحص</dt><dd>{task.requested_by}</dd></div><div><dt>المفتش</dt><dd>{task.assignee || 'بانتظار التعيين'}</dd></div><div><dt>إنشاء الطلب</dt><dd>{date(task.created_at)}</dd></div><div><dt>موعد الفحص</dt><dd>{date(task.scheduled_at)}</dd></div><div><dt>القفص</dt><dd dir="ltr">CAGE-{String(task.number).padStart(3, '0')}</dd></div><div><dt>الشاحنة</dt><dd dir="ltr">{trip.truck}</dd></div></dl><button onClick={() => onSeraj(trip)}>تفاصيل السراج وقراءات رحلته<ArrowLeft size={16}/></button></section>

      <section className="panel lpg-inspection-assessment"><div className="lpg-inspection-heading"><h3><ShieldCheck size={18}/>تقييم حالة السراج</h3><span className={`lpg-task-condition ${task.condition}`}>{conditions[task.condition]}</span></div>{task.assessment ? <><p className="lpg-inspection-note">آخر تقييم محفوظ · {task.assessment.by} · {date(task.assessment.at)}</p><dl className="lpg-inspection-checks"><div><dt>فحص منطقة LPG</dt><dd>{gasChecks[task.assessment.gas_check]}</dd></div><div><dt>تثبيت السراج والقفص</dt><dd>{mountChecks[task.assessment.mount_check]}</dd></div><div><dt>حالة القفل</dt><dd>{latchChecks[task.assessment.latch_check]}</dd></div></dl><h4>نتيجة الفحص</h4><p className="lpg-inspection-text">{task.assessment.findings}</p><h4>التوصية</h4><p className="lpg-inspection-text">{task.assessment.recommendation}</p></> : <p className="lpg-inspection-note">لم يسجل المفتش تقييمًا بعد. قراءات السراج أدناه توضح الملاحظات التي تُراجع أثناء الفحص.</p>}{task.decision && <div className="lpg-inspection-decision"><strong>{task.status === 'cancelled' ? 'سبب الإلغاء' : 'قرار الفحص'}</strong><p>{task.decision}</p></div>}
        <div className="lpg-inspection-actions">{canEvaluate && task.status === 'new' && <button className="primary" disabled={busy} onClick={() => startAction('assign')}><UserRound size={16}/>تعيين مفتش وبدء الفحص</button>}{canEvaluate && task.status === 'in_progress' && <button className="primary" disabled={busy} onClick={() => startAction('result')}>تسجيل تقييم السراج</button>}{canEvaluate && task.status === 'review' && <><button className="primary" disabled={busy} onClick={() => startAction('close')}>اعتماد القرار وإغلاق المهمة</button><button disabled={busy} onClick={() => startAction('result')}>تعديل التقييم</button><button disabled={busy} onClick={() => startAction('assign')}>إعادة الفحص</button></>}{canEvaluate && ['new', 'in_progress'].includes(task.status) && <button disabled={busy} onClick={() => startAction('cancel')}>إلغاء الطلب</button>}</div>
        {action && <form className="lpg-inspection-action-form" key={`${task.id}-${action}`} onSubmit={submitAction}><h4>{action === 'assign' ? 'تعيين المفتش' : action === 'result' ? 'تسجيل نتيجة الفحص وتقييم الحالة' : action === 'close' ? 'اعتماد قرار المهمة' : 'إلغاء الطلب'}</h4>{action === 'assign' ? <label>اسم المفتش<input name="assignee" defaultValue={task.assignee} required maxLength={100}/></label> : action === 'result' ? <><div className="lpg-inspection-form-grid"><label>تقييم الحالة<select name="condition" required defaultValue={task.assessment?.condition || ''}><option value="" disabled>اختر تقييم الحالة</option>{Object.entries(conditions).filter(([id]) => id !== 'pending').map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>فحص منطقة LPG<select name="gas_check" defaultValue={task.assessment?.gas_check || 'not_checked'}>{Object.entries(gasChecks).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>تثبيت السراج والقفص<select name="mount_check" defaultValue={task.assessment?.mount_check || 'not_checked'}>{Object.entries(mountChecks).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>حالة القفل<select name="latch_check" defaultValue={task.assessment?.latch_check || 'not_checked'}>{Object.entries(latchChecks).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label></div><label>نتيجة الفحص والملاحظات<textarea name="findings" required minLength={3} maxLength={4000} defaultValue={task.assessment?.findings || ''}/></label><label>التوصية والإجراء المطلوب<textarea name="recommendation" required minLength={3} maxLength={2000} defaultValue={task.assessment?.recommendation || ''}/></label></> : <label>{action === 'close' ? 'قرار الإغلاق والإجراء المتخذ' : 'سبب الإلغاء'}<textarea name="decision" required minLength={3} maxLength={2000}/></label>}<div className="lpg-inspection-actions"><button className="primary" disabled={busy} type="submit">{busy ? 'جاري الحفظ…' : 'حفظ'}</button><button type="button" disabled={busy} onClick={() => setAction(null)}>إلغاء التعديل</button></div></form>}
      </section>

      <section className="panel lpg-inspection-evidence"><div className="lpg-inspection-heading"><h3><Activity size={18}/>قراءات السراج المرتبطة بطلب الفحص</h3><span>لقطة <b dir="ltr">{n(task.evidence_until_s / 60)} دقيقة</b></span></div>{evidenceError ? <p role="alert">تعذر تحميل القراءات. <button onClick={() => setRetry(v => v + 1)}>إعادة المحاولة</button></p> : !evidence ? <p role="status">جاري حساب ملخص القراءات…</p> : <><p className={`lpg-inspection-preliminary ${evidence.expected_state}`}>{evidence.expected_state === 'review' ? 'توجد ملاحظات في منطقة القفص تستحق الفحص.' : evidence.expected_state === 'unknown' ? 'القراءات لا تكفي لتقدير حالة السراج؛ يلزم التحقق من الاتصال والحساسات.' : 'لم يسجل التحليل ملاحظة مؤكدة في القراءات المتاحة.'}<span>تغطية القياسات <b dir="ltr">{n(evidence.coverage_percent)}%</b></span></p><dl className="lpg-inspection-peaks">{[['temperature', 'أعلى حرارة', '°C'], ['lpg', 'أعلى LPG', 'ppm'], ['strain_a', 'أقصى انفعال A', 'µε'], ['shock', 'أعلى تسارع', 'g']].map(([key, label, unit]) => <div key={key}><dt>{label}</dt><dd dir="ltr">{evidence.peaks[key] ? n(evidence.peaks[key]!.value, key === 'lpg' ? 4 : key === 'shock' ? 2 : 1) : '—'} <small>{unit}</small></dd></div>)}</dl><div className="lpg-inspection-table-wrap"><table><thead><tr><th scope="col">القناة</th><th scope="col">الملاحظة في لقطة الطلب</th><th scope="col">أعلى درجة</th></tr></thead><tbody>{Object.entries(evidence.signals).map(([id, signal]) => <tr key={id}><th scope="row">{heads[id]}</th><td>{signal.confirmed ? 'إشارة مؤكدة في القراءات' : signal.latest_state === 'unknown' ? 'البيانات غير مكتملة' : 'لا إشارة مؤكدة'}</td><td dir="ltr">{signal.max_score == null ? '—' : n(signal.max_score, 3)}</td></tr>)}</tbody></table></div><p className="lpg-inspection-note">الصدمات: {n(evidence.shock_events, 0)} واقعة · فتح القفل: {n(evidence.lock_open_events, 0)} مرة. القياسات مشتركة للقفص وتساعد المفتش في تحديد ما يحتاج المراجعة.</p></>}</section>

      <section className="panel lpg-inspection-history"><div className="lpg-inspection-heading"><h3><History size={18}/>سجل إجراءات المهمة</h3></div><ol>{[...task.history].reverse().map((item, index) => <li key={`${item.at}-${index}`}><span className={`lpg-task-status ${item.status}`}>{statuses[item.status]}</span><div><strong>{item.actor}</strong><p>{item.note}</p></div><time>{date(item.at)}</time></li>)}</ol></section>
    </> : !tasks.length && <section className="panel"><h3>لا توجد طلبات فحص لسروج الشحنات</h3><p>أنشئ طلبًا من هذه الصفحة أو من تفاصيل السرج.</p></section>}</div>

    <aside className="panel lpg-inspection-directory" aria-label="السروج المطلوب فحصها"><div className="lpg-inspection-heading"><h3><ClipboardList size={18}/>السروج المطلوب فحصها</h3><span>{n(visible.length, 0)}</span></div><label className="lpg-inspection-search"><Search size={16}/><input aria-label="البحث في مهام فحص الشحنات" placeholder="رقم السرج أو المدينة" value={query} onChange={e => setQuery(e.target.value)}/></label><select aria-label="تصفية مهام فحص الشحنات" value={filter} onChange={e => setFilter(e.target.value)}><option value="open">المهام المفتوحة</option><option value="all">جميع المهام</option>{Object.entries(statuses).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><div className="lpg-inspection-task-list">{visible.map(item => <button aria-label={`فتح فحص ${item.saddle_id} ${item.id}`} key={item.id} className={task?.id === item.id ? 'selected' : ''} aria-current={task?.id === item.id ? 'true' : undefined} onClick={() => { setNewOpen(false); setNotice(''); onSelect(item.id); }}><div><strong dir="ltr">{item.saddle_id}</strong><span className={`lpg-task-priority ${item.priority}`}>{priorities[item.priority]}</span></div><p>{trips.find(t => t.id === item.trip_id)?.destination.city} · <b dir="ltr">{item.trip_id}</b></p><span className={`lpg-task-status ${item.status}`}>{statuses[item.status]}</span><small className={`lpg-task-condition ${item.condition}`}>{conditions[item.condition]}</small></button>)}</div>{!visible.length && <p className="lpg-inspection-note">لا توجد مهمة تطابق التصفية الحالية.</p>}</aside></div>
    <details className="lpg-inspection-source"><summary><Info size={15}/>مصدر الطلبات والتقييمات</summary><p>الطلبات الأولية والتقييمات المحفوظة فيها أمثلة عرض لسروج الشحنات الجديدة. الطلبات والتقييمات التي تُدخلها هنا تُحفظ مع سجل الإجراءات في قسم مستقل. ملخص القراءات محسوب من محاكي السراج والتحليل السابق 416 حتى زمن لقطة الطلب، وقناة H₂S ممثلة باسم LPG. لم يُدرّب النموذج بعد على شحنات LPG. التقييم يخص السراج والقفص؛ الفحص الفردي يحدد حالة الأسطوانات.</p></details>
  </div>;
}
