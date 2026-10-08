import { DISPLAY_LOCALE } from './locale';
import './saddle-ai.css';

const heads: Record<string,string> = {
  mechanical_anomaly: 'الانفعال المرتبط بالشقوق',
  thermal_anomaly: 'الشذوذ الحراري',
  wetness_anomaly: 'البلل ومراجعة الطلاء',
  h2s_anomaly: 'غاز H₂S',
};

export default function SaddleAI({result}: {result:any}) {
  if (!result) return <p className="ai-waiting">التحليل التلقائي جاهز؛ بانتظار تشغيل أو دفعة قراءات جديدة لهذا السرج.</p>;
  const status = result.status;
  return <div className="saddle-ai-result">
    <div className="saddle-ai-meta"><strong>XGBoost · 416</strong><span>{status === 'active' ? 'تحليل تلقائي' : status === 'warming_up' ? `تهيئة ${result.baseline_collected} / 24` : 'الاستنتاج معلّق'}</span></div>
    {result.reason && <p className="ai-waiting" role="status">{result.reason}</p>}
    <table className="saddle-ai-table" aria-label="نتائج النموذج المستقلة لقنوات السرج">
      <thead><tr><th scope="col">المسار</th><th scope="col">الحالة</th><th scope="col">درجة النموذج</th></tr></thead>
      <tbody>{Object.entries(heads).map(([key,label]) => {
        const signal = result.signals?.[key];
        const state = signal?.state || 'unknown';
        const text = state === 'unknown' ? 'غير متاح' : signal.alarm ? 'تنبيه مؤكد' : state === 'present' ? 'بانتظار التأكيد' : 'لا تظهر إشارة';
        return <tr key={key}><th scope="row">{label}</th><td><span className={`ai-signal ${state}`}><i aria-hidden="true"/>{text}</span></td><td dir="ltr">{typeof signal?.score === 'number' ? signal.score.toLocaleString(DISPLAY_LOCALE,{maximumFractionDigits:3}) : '—'}</td></tr>;
      })}</tbody>
    </table>
    <p className="ai-footnote">الدرجات ليست احتمالات معايرة. الحالة تمثل آخر قراءة؛ التنبيهات السابقة تبقى في السجل للمراجعة.</p>
  </div>;
}
