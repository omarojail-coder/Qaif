import { guestEvidence } from './guestEvidence.ts';
import type { GuestDemo, GuestJourney } from './guestEvidence.ts';

type Bundle = { demo: GuestDemo; passports: Record<string, { journeys: GuestJourney[] }>; reports: Record<string, unknown> };
const pending = new Map<string, Promise<any>>();
async function read<T = any>(name: string): Promise<T> {
  if (!pending.has(name)) {
    const request = fetch(`/guest-data/${name}.json`).then(async response => {
      if (!response.ok) throw new Error('تعذر تحميل بيانات العرض؛ أعد المحاولة.');
      return response.json();
    }).catch(error => { pending.delete(name); throw error; });
    pending.set(name, request);
  }
  return pending.get(name)!;
}
function numberFromSerial(serial: string) {
  const match = /^CYL-(\d{3})-(\d{2})$/.exec(serial);
  if (!match || +match[1] < 1 || +match[1] > 21 || +match[2] < 1 || +match[2] > 9) throw new Error('الرقم التسلسلي غير موجود في سجل العرض.');
  return +match[1];
}
const bundle = (number: number) => read<Bundle>(`seraj-${number}`);

export async function guestApi<T>(path: string, body?: unknown, method?: string): Promise<T> {
  if ((method || (body === undefined ? 'GET' : 'POST')).toUpperCase() !== 'GET' || body !== undefined) {
    throw new Error('وضع الزائر للعرض فقط؛ التعديل يحتاج حسابًا وخادم النظام.');
  }
  const url = new URL(path, 'https://guest.invalid'), route = decodeURIComponent(url.pathname);
  let result: unknown;
  if (route === '/auth/me') result = { id: 'guest', name: 'زائر قائف', role: 'viewer' };
  else if (route === '/snapshot') {
    const { tasks } = await read('inspections');
    const catalog = await read('catalog');
    result = {
      ...Object.fromEntries(['assets', 'pipelines', 'alerts', 'missions', 'captures', 'analyses', 'reports', 'inspections', 'documents', 'source_events', 'placements', 'episodes'].map(key => [key, []])),
      saddles: Array.from({ length: 21 }, (_, i) => ({ id: `S-${i+1}`, name: `سراج الشحنة S-${i+1}`, trip_id: `TRIP-${String(i+1).padStart(3, '0')}` })),
      cylinders: catalog.cylinders.map((c: { serial: string }) => ({ id: c.serial, name: c.serial })),
      lpg_inspections: tasks,
      config: { guest_mode: true, demo_mode: true, public_deployment: true, demo_login_enabled: false, gemini_ready: false, camera_connected: false, saved_visual_results: 0, visual_cache_fallback_enabled: false },
    };
  } else if (route === '/lpg/demo/cylinders') result = await read('catalog');
  else if (route === '/lpg/inspections') result = (await read('inspections')).tasks;
  else {
    const seraj = /^\/lpg\/demo\/seraj\/(\d+)$/.exec(route);
    const cylinder = /^\/lpg\/demo\/cylinders\/([^/]+)(?:\/journeys\/([^/]+))?$/.exec(route);
    const report = /^\/public\/cylinders\/([^/]+)\/report$/.exec(route);
    const inspection = /^\/lpg\/inspections\/(LPG-F-\d{3})\/evidence$/.exec(route);
    if (seraj && +seraj[1] >= 1 && +seraj[1] <= 21) result = (await bundle(+seraj[1])).demo;
    else if (cylinder) {
      const serial = cylinder[1], data = await bundle(numberFromSerial(serial));
      const passport = data.passports[serial];
      if (!cylinder[2]) result = passport;
      else {
        const journey = passport.journeys.find(j => j.id === cylinder[2]);
        if (!journey) throw new Error('الرحلة المطلوبة غير موجودة لهذه الأسطوانة.');
        const rawCutoff = url.searchParams.get('until_s');
        const until = rawCutoff === null ? 1200 : Number(rawCutoff);
        if (!Number.isFinite(until)) throw new Error('وقت القراءات غير صالح.');
        result = guestEvidence(serial, journey, (await bundle(journey.scenario_number)).demo, until);
      }
    } else if (report) result = (await bundle(numberFromSerial(report[1]))).reports[report[1]];
    else if (inspection) {
      result = (await read('inspections')).evidence[inspection[1]];
      if (!result) throw new Error('مهمة الفحص المطلوبة غير موجودة.');
    } else throw new Error('هذه الخدمة تحتاج خادم النظام؛ المتاح للزائر هو نوافذ عرض LPG.');
  }
  return structuredClone(result) as T;
}
