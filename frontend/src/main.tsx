import React, { useEffect, useId, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Map as MapIcon,
  ClipboardList,
  ScanLine,
  Cylinder,
  Plane,
  CheckSquare,
  Search,
  Bell,
  Plus,
  ChevronLeft,
  X,
  Settings,
  Activity,
  FileText,
  Upload,
  Link as LinkIcon,
  ArrowLeft,
  CircleCheck,
  Clock,
  TriangleAlert,
  Thermometer,
  Waves,
  Radio,
  ShieldCheck,
  LogOut,
  Menu,
  Play,
  Download,
  Eye,
  History,
  Layers,
  MapPin,
  UserRound,
  CalendarDays,
} from "lucide-react";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import { api } from "./api";
import { DISPLAY_LOCALE } from "./locale";
import type { RecordData, Snapshot } from "./api";
import Chart from "./Chart";
import LpgMapPage from "./LpgMapPage";
import LpgSaddleDashboard from "./LpgSaddleDashboard";
import LpgCylindersPage from "./LpgCylindersPage";
import LpgInspectionsPage from "./LpgInspectionsPage";
import LpgCustomerReport from "./LpgCustomerReport";
import { loadShipmentTrips, pageFromHash, readShipmentSelection, saveShipmentSelection } from "./lpgTripSelection";
import type { ShipmentTrip } from "./lpgMapData";
import FacilityIcon from "./FacilityIcon";
import MetricIcon from "./MetricIcon";
import CapturePair from "./CapturePair";
import SaddleAI from "./SaddleAI";
import SaddleMiniMap from "./SaddleMiniMap";
import DroneFlightMap from "./DroneFlightMap";
import { saddleStatus } from "./saddleMarkers";
import ArrivalPhotos from "./ArrivalPhotos";
import useTransientFlightPhotos from "./useTransientFlightPhotos";
import { flightPhotoKey } from "./transientFlightPhotos";
import "./style.css";
import "./refresh.css";

const labels: { [key: string]: string } = {
  new: "جديدة",
  scheduled: "مجدولة",
  in_progress: "قيد التنفيذ",
  review: "قيد المراجعة",
  completed: "مكتملة",
  cancelled: "ملغاة",
  assigned: "تم التعيين",
  visited: "تمت الزيارة",
  result: "نتيجة مسجلة",
  closed: "مغلقة",
  acknowledged: "تم الاطلاع",
  good: "جيدة",
  degraded: "تحتاج مراجعة",
  no_data: "لا توجد قراءات",
  operator: "مشغّل الأصول",
  drone: "مشغّل الدرون",
  inspector: "مفتش",
  admin: "مدير النظام",
  rgb: "صور عادية RGB",
  thermal: "صور حرارية",
  both: "عادية وحرارية",
  human: "مراجعة بشرية",
  gemini: "Gemini",
  simulation: "محاكاة",
  manual_demo: "إشارة اختبار يدوية",
  uploaded: "صورة مرفوعة",
  camera_export: "تصدير كاميرا",
  prepared_demo: "صورة مُعدة للعرض",
  high: "عالية",
  medium: "متوسطة",
  low: "منخفضة",
  imported: "بيانات مستوردة",
  device: "بيانات جهاز",
  crack_like: "مظهر شبيه بالشق",
  coating: "الطلاء",
  corrosion_like: "مظهر شبيه بالتآكل",
  other: "ملاحظة أخرى",
  none: "لا يوجد مظهر محدد",
  draft: "مسودة",
  reviewed: "راجعه المفتش",
  approved: "معتمد",
  rejected: "مرفوض",
  failed: "تعذر التحليل",
};
const pages = [
  ["map", "الخريطة", MapIcon],
  ["saddle", "تفاصيل السرج", ClipboardList],
  ["cylinders", "سجل الأسطوانات", Cylinder],
  ["inspection", "مهام الفحص", CheckSquare],
  ["sources", "التقارير والسجل", FileText],
  ["demo", "المحاكي", Activity],
] as const;
const fmt = (date?: string) =>
  date
    ? new Date(date).toLocaleString(DISPLAY_LOCALE, {
        dateStyle: "short",
        timeStyle: "short",
        calendar: "gregory",
      })
    : "لم يحدد";
const n = (value: any, digits = 1) =>
  typeof value === "number"
    ? value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: digits })
    : "—";
const idShort = (id?: string) =>
  id ? (/^[DC]-v33-s\d+/.test(id) ? id.replace("-v33-", "-") : id.slice(0, 8)).toUpperCase() : "—";
function Badge({
  value,
  children,
}: {
  value: string;
  children?: React.ReactNode;
}) {
  return (
    <span className={`badge ${value}`}>
      <span className="badge-dot" />
      {children || labels[value] || value}
    </span>
  );
}
function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Layers size={30} />
      <h3>{title}</h3>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  );
}
function Panel({ title, icon: Icon = FileText, children, action }: any) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h3>
          <Icon size={18} />
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}
function Field({
  label,
  name,
  defaultValue = "",
  required = true,
  type = "text",
  area = false,
  placeholder = "",
}: any) {
  return (
    <label className="field">
      <span>{label}</span>
      {area ? (
        <textarea
          name={name}
          defaultValue={defaultValue}
          required={required}
          placeholder={placeholder}
          rows={3}
          maxLength={4000}
        />
      ) : (
        <input
          type={type}
          name={name}
          defaultValue={defaultValue}
          required={required}
          placeholder={placeholder}
          maxLength={2000}
        />
      )}
    </label>
  );
}
function Select({ label, name, children, defaultValue = "", onChange }: any) {
  return (
    <label className="field">
      <span>{label}</span>
      <select name={name} defaultValue={defaultValue} onChange={onChange}>
        {children}
      </select>
    </label>
  );
}
function Modal({ title, children, close }: any) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog ref={ref} onCancel={close} className="modal" aria-label={title}>
      <div className="modal-heading">
        <h2>{title}</h2>
        <button className="icon-button" onClick={close} aria-label="إغلاق">
          <X size={21} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function Brand({ large = false }: { large?: boolean }) {
  const gradientId = useId();
  return (
    <div className={`brand ${large ? "large" : ""}`}>
      <svg
        className="brand-mark"
        width="52"
        height="46"
        viewBox="234 290 790 665"
        aria-label="شعار قائف"
        role="img"
      >
        <defs>
          <linearGradient id={`${gradientId}-purple`} gradientUnits="userSpaceOnUse" x1="305" y1="325" x2="1011" y2="510">
            <stop stopColor="#A98CF6" />
            <stop offset="1" stopColor="#7552D8" />
          </linearGradient>
          <linearGradient id={`${gradientId}-pink`} gradientUnits="userSpaceOnUse" x1="260" y1="360" x2="690" y2="425">
            <stop stopColor="#FA9AB9" />
            <stop offset="1" stopColor="#F280A4" />
          </linearGradient>
          <linearGradient id={`${gradientId}-blue`} gradientUnits="userSpaceOnUse" x1="355" y1="550" x2="892" y2="729">
            <stop stopColor="#6772E8" />
            <stop offset="1" stopColor="#3E4DC9" />
          </linearGradient>
          <linearGradient id={`${gradientId}-light-blue`} gradientUnits="userSpaceOnUse" x1="300" y1="560" x2="745" y2="650">
            <stop stopColor="#96AEFF" />
            <stop offset="1" stopColor="#758FFA" />
          </linearGradient>
          <linearGradient id={`${gradientId}-orange`} gradientUnits="userSpaceOnUse" x1="345" y1="790" x2="748" y2="915">
            <stop stopColor="#FA965A" />
            <stop offset="1" stopColor="#F58439" />
          </linearGradient>
          <linearGradient id={`${gradientId}-salmon`} gradientUnits="userSpaceOnUse" x1="320" y1="915" x2="655" y2="780">
            <stop stopColor="#EA9698" />
            <stop offset="1" stopColor="#D57B7D" />
          </linearGradient>
        </defs>
        <path
          fill={`url(#${gradientId}-purple)`}
          d="M247 596V482C247 383 327 302 428 302H904C963 302 1011 350 1011 406C1011 463 963 510 904 510H448C355 510 297 545 251 596C248 600 247 598 247 596Z"
        />
        <path
          fill={`url(#${gradientId}-pink)`}
          d="M247 596V482C247 383 327 302 428 302H718C633 313 555 357 492 406C420 459 366 479 329 496C278 519 249 561 247 596Z"
        />
        <path
          fill={`url(#${gradientId}-blue)`}
          d="M390 549H802C852 549 892 589 892 639C892 689 852 729 802 729H390C340 729 300 689 300 639C300 589 340 549 390 549Z"
        />
        <path
          fill={`url(#${gradientId}-light-blue)`}
          d="M390 549H802C688 559 627 594 578 636C514 690 430 724 349 728C321 717 300 682 300 639C300 589 340 549 390 549Z"
        />
        <path
          fill={`url(#${gradientId}-orange)`}
          d="M403 765H658C708 765 748 805 748 855C748 905 708 945 658 945H403C353 945 313 905 313 855C313 805 353 765 403 765Z"
        />
        <path
          fill={`url(#${gradientId}-salmon)`}
          d="M403 765H658C612 770 597 807 564 846C526 900 452 933 382 943C343 934 313 898 313 855C313 805 353 765 403 765Z"
        />
      </svg>
      <strong>قائف</strong>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<any>(undefined);
  const [data, setData] = useState<Snapshot | null>(null);
  const [page, setPage] = useState(pageFromHash);
  const [selected, setSelected] = useState("S-12");
  const [shipmentSelection, setShipmentSelection] = useState<ShipmentTrip | null>(readShipmentSelection);
  const [shipmentTrips, setShipmentTrips] = useState<ShipmentTrip[]>([]);
  const [shipmentError, setShipmentError] = useState("");
  const [shipmentRetry, setShipmentRetry] = useState(0);
  const [routeHash, setRouteHash] = useState(location.hash);
  const shipmentRouteId = new URLSearchParams(routeHash.split('?')[1]).get('trip');
  const cylinderRouteSerial = new URLSearchParams(routeHash.split('?')[1]).get('serial');
  const [assetCategory, setAssetCategory] = useState("gas");
  const [search, setSearch] = useState("");
  const [globalSearch, setGlobalSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedMission, setSelectedMission] = useState("");
  const [selectedInspection, setSelectedInspection] = useState("");
  const [selectedCapture, setSelectedCapture] = useState("");
  const [compareCapture, setCompareCapture] = useState("");
  const [savedAnalysis, setSavedAnalysis] = useState<{ captureId: string; previousId: string; available: boolean } | null>(null);
  const [episode, setEpisode] = useState<any>(null);
  const [channel, setChannel] = useState("strain");
  const [modal, setModal] = useState<any>(null);
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [flightClockOffset, setFlightClockOffset] = useState(0);
  const [sendingDrone, setSendingDrone] = useState(false);
  const droneDispatchPending = useRef(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [isMobile, setIsMobile] = useState(
    matchMedia("(max-width:640px)").matches,
  );
  useEffect(() => {
    const media = matchMedia("(max-width:640px)");
    const listener = () => setIsMobile(media.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);
  const [live, setLive] = useState(false);
  const [notifications, setNotifications] = useState(false);

  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => setUser(null));
  }, []);
  const refresh = async () => {
    const snapshot = await api<Snapshot>("/snapshot");
    setData(snapshot);
  };
  useEffect(() => {
    if (user)
      refresh().catch((e) => setToast({ text: e.message, error: true }));
  }, [user]);
  useEffect(() => {
    const listener = () => {
      setPage(pageFromHash());
      setRouteHash(location.hash);
      setShipmentSelection(readShipmentSelection());
      setSearch("");
      setStatusFilter("all");
    };
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (page !== 'saddle') return;
    let alive = true;
    setShipmentError('');
    loadShipmentTrips().then(trips => {
      if (!alive) return;
      setShipmentTrips(trips);
      const saved = readShipmentSelection();
      const target = shipmentRouteId || saved?.id || trips[0].id;
      const trip = trips.find(t => t.id === target);
      if (!trip) {
        setShipmentSelection(null);
        setShipmentError('الرحلة المطلوبة غير موجودة. اختر سراجًا من القائمة.');
        return;
      }
      const chosen = saveShipmentSelection(saved?.id === trip.id ? saved : trip);
      setShipmentSelection(chosen);
    }).catch(error => { if (alive) setShipmentError(error.message); });
    return () => { alive = false; };
  }, [page, shipmentRouteId, shipmentRetry]);
  useEffect(() => {
    if (!user) return;
    let ws: WebSocket;
    let retry: ReturnType<typeof setTimeout>;
    let stopped = false;
    let pulse: ReturnType<typeof setInterval>;
    const connect = () => {
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/events`,
      );
      ws.onopen = () => {
        setLive(true);
        pulse = setInterval(
          () => ws.readyState === 1 && ws.send("ping"),
          25000,
        );
      };
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "changed") refresh().catch(() => {});
      };
      ws.onclose = () => {
        setLive(false);
        clearInterval(pulse);
        if (!stopped) retry = setTimeout(connect, 4000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(pulse);
      ws?.close();
    };
  }, [user]);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(
        () => setToast(null),
        toast.error ? 12000 : 6000,
      );
      return () => clearTimeout(timer);
    }
  }, [toast]);
  const saddles: RecordData[] = data?.saddles || [];
  const saddle: RecordData = saddles.find((s) => s.id === selected) ||
    saddles.find((s) => s.id === "S-12") || { id: "", name: "نقطة غير محددة" };
  const assets: RecordData[] = data?.assets || [];
  const alerts: RecordData[] = data?.alerts || [];
  const missions: RecordData[] = data?.missions || [];
  const transientPhotos = useTransientFlightPhotos(missions, flightClockOffset);
  const captures: RecordData[] = data?.captures || [];
  const analyses: RecordData[] = data?.analyses || [];
  const inspections: RecordData[] = data?.inspections || [];
  const reports: RecordData[] = data?.reports || [];
  const sourceEvents: RecordData[] = data?.source_events || [];
  const activeAlerts = alerts.filter((a) => a.status === "new");
  const [mapPipeline, setMapPipeline] = useState("");
  const [mapRail, setMapRail] = useState("assets");
  const [mapPoints, setMapPoints] = useState("all");
  const prioritySaddles = saddles
    .filter(
      (s) =>
        activeAlerts.some((a) => a.saddle_id === s.id) ||
        s.quality === "degraded",
    )
    .sort(
      (a, b) =>
        Number(
          activeAlerts.some(
            (x) => x.saddle_id === b.id && x.priority === "high",
          ),
        ) -
        Number(
          activeAlerts.some(
            (x) => x.saddle_id === a.id && x.priority === "high",
          ),
        ),
    );
  const saddleAlerts = alerts.filter((a) => a.saddle_id === saddle?.id);
  const saddleHasAlert = saddleStatus(saddle, alerts) === "alert";
  const saddlePhotoMission = missions.find(
    (m) =>
      m.saddle_id === saddle?.id && captures.some((c) => c.mission_id === m.id),
  );
  const saddlePhotos = captures.filter(
    (c) => c.mission_id === saddlePhotoMission?.id,
  );
  const mission = missions.find((m) => m.id === selectedMission) || missions[0];
  const inspection =
    inspections.find((i) => i.id === selectedInspection) || inspections[0];
  const missionCaptures = captures.filter((c) => c.mission_id === mission?.id);
  const arrivalPhotos = mission ? transientPhotos[flightPhotoKey(mission)] || [] : [];
  const capture =
    missionCaptures.find((c) => c.id === selectedCapture) || missionCaptures[0];
  const captureAnalyses = analyses.filter((a) => a.capture_id === capture?.id);
  const previous = captures.find((c) => c.id === compareCapture);
  useEffect(() => {
    let cancelled = false;
    setSavedAnalysis(null);
    if (user && capture?.id && data?.config.visual_cache_fallback_enabled) {
      const query = compareCapture ? "?previous_id=" + encodeURIComponent(compareCapture) : "";
      api("/captures/" + capture.id + "/analysis-cache" + query)
        .then((value) => {
          if (!cancelled) setSavedAnalysis({ captureId: capture.id, previousId: compareCapture, available: value.available });
        })
        .catch(() => {});
    }
    return () => { cancelled = true; };
  }, [user, capture?.id, compareCapture, data?.analyses, data?.config.visual_cache_fallback_enabled]);
  const savedAvailable = !!(savedAnalysis?.available && savedAnalysis.captureId === capture?.id && savedAnalysis.previousId === compareCapture);
  const nameOf = (saddleId: string) =>
    saddles.find((s) => s.id === saddleId)?.name || saddleId;
  const goto = (next: string) => {
    location.hash = next;
    setRouteHash(location.hash);
    setPage(pageFromHash());
    setMobileNav(false);
    setSearch("");
    setStatusFilter("all");
  };
  const choose = (id: string) => {
    setShipmentSelection(null);
    setSelected(id);
    if (id.startsWith("S-")) goto("pipe-saddle");
  };
  useEffect(() => {
    let cancelled = false;
    setEpisode((previous: any) =>
      previous?.id === saddle?.episode_id ? previous : null,
    );
    if (saddle?.episode_id)
      api("/episodes/" + saddle.episode_id)
        .then((value) => {
          if (!cancelled) setEpisode(value);
        })
        .catch((e) => setToast({ text: e.message, error: true }));
    return () => {
      cancelled = true;
    };
  }, [saddle?.episode_id, saddle?.updated_at]);
  const run = async (
    work: () => Promise<any>,
    message: string | ((result: any) => string) = "تم حفظ التغيير",
    close = true,
  ) => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await work();
      await refresh();
      if (close) setModal(null);
      setToast({ text: typeof message === "function" ? message(result) : message });
      return result;
    } catch (e: any) {
      setToast({ text: e.message, error: true });
    } finally {
      setBusy(false);
    }
  };
  const form = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    return Object.fromEntries(new FormData(event.currentTarget));
  };
  const submitTransition = (kind: string, item: RecordData, target: string) =>
    setModal({ type: "transition", kind, item, target });
  const newMission = (saddleId = saddle?.id, alertId?: string) =>
    setModal({ type: "mission", saddleId, alertId });
  const newInspection = (saddleId = saddle?.id, reportId?: string) =>
    setModal({ type: "inspection", saddleId, reportId });
  const can = (...roles: string[]) =>
    user?.role === "admin" || roles.includes(user?.role);
  const sendDrone = async (alert?: RecordData) => {
    if (droneDispatchPending.current || busy || !saddleHasAlert || !can("operator", "drone")) return;
    droneDispatchPending.current = true;
    setSendingDrone(true);
    setBusy(true);
    const target = saddle;
    try {
      const created = await api<RecordData>("/missions", {
        saddle_id: target.id,
        alert_id: alert?.id || null,
        image_type: "both",
        reason: (alert ? `فحص السرج بعد تنبيه: ${alert.title}` : `فحص ${target.name} بعد تنبيه السرج`).slice(0, 2000),
      });
      // Show the created mission immediately, even if the following snapshot is unavailable.
      setData(previous => previous ? {
        ...previous,
        missions: [created, ...(previous.missions || []).filter((item: RecordData) => item.id !== created.id)],
      } : previous);
      setSelectedMission(created.id);
      setSelectedCapture("");
      setCompareCapture("");
      goto("pipe-drone");
      setToast({ text: `بدأت رحلة الدرون إلى ${target.name}` });
      requestAnimationFrame(() => {
        const panel = document.querySelector(`[data-mission-id="${created.id}"].drone-flight-panel`);
        if (panel) window.scrollTo({ top: window.scrollY + panel.getBoundingClientRect().top - 80 });
      });
      await refresh().catch(() => {});
    } catch (error: any) {
      setToast({ text: error.message, error: true });
    } finally {
      droneDispatchPending.current = false;
      setSendingDrone(false);
      setBusy(false);
    }
  };
  const filterItems = (items: RecordData[]) =>
    items.filter(
      (item) =>
        (statusFilter === "all" || item.status === statusFilter) &&
        (nameOf(item.saddle_id) + item.id + (item.reason || "")).includes(
          search,
        ),
    );

  if (user === undefined)
    return (
      <div className="loading">
        <Brand large />
        <p>جاري تحميل قائف…</p>
      </div>
    );
  if (!user)
    return (
      <div className="login-page">
        <div className="login-intro">
          <Brand large />
          <h1>من الإشارة إلى القرار.</h1>
          <p>تابع قراءات السرج، واربط صور الدرون والفحص بسجل واحد للأصل.</p>
          <div className="login-steps">
            <span>
              <Radio />
              قراءات
            </span>
            <ArrowLeft />
            <span>
              <Plane />
              تصوير
            </span>
            <ArrowLeft />
            <span>
              <ShieldCheck />
              قرار
            </span>
          </div>
        </div>
        <section className="login-card">
          <h2>الدخول إلى المنصة</h2>
          <form
            onSubmit={(e) => {
              const values = form(e);
              run(async () => {
                const result = await api("/auth/login", values);
                setUser(result);
              }, "تم تسجيل الدخول");
            }}
          >
            <Field label="اسم المستخدم" name="name" />
            <Field label="كلمة المرور" name="password" type="password" />
            <button className="primary" disabled={busy}>
              تسجيل الدخول
            </button>
          </form>
          {["localhost", "127.0.0.1", "[::1]"].includes(location.hostname) && <div className="demo-login">
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  setUser(await api("/auth/demo?role=admin", {}));
                }, "تم فتح مساحة العمل")
              }
            >
              دخول سريع <ArrowLeft size={17} />
            </button>
            <small>يُعطّل هذا الدخول عند النشر العام.</small>
          </div>}
        </section>
        {toast && (
          <div className="toast error" role="alert">
            {toast.text}
          </div>
        )}
      </div>
    );
  if (!data)
    return (
      <div className="loading">
        <Brand large />
        <p>جاري تحميل الأصول…</p>
        {toast && (
          <p role="alert">
            {toast.text}
            <button onClick={() => refresh()}>إعادة المحاولة</button>
          </p>
        )}
      </div>
    );

  const headline = page === 'pipe-saddle' ? 'سجل سرج الأنابيب' : page === 'pipe-drone' ? 'جولات الدرون السابقة' : page === 'pipe-inspection' ? 'مهام فحص الأنابيب السابقة' : page === 'pipe-sources' ? 'تقارير الأنابيب السابقة' : pages.find((p) => p[0] === page)?.[1] || "الإعدادات";
  const shellTitle = (subtitle: string, action?: React.ReactNode) => (
    <div className="page-heading">
      <div>
        <h1>{headline}</h1>
        <p>{subtitle}</p>
      </div>
      {action}
    </div>
  );
  const taskRail = (kind: "mission" | "inspection") => {
    const items = kind === "mission" ? missions : inspections;
    const selectedItem = kind === "mission" ? mission : inspection;
    return (
      <aside className="list-rail">
        <div className="list-heading">
          <h2>{kind === "mission" ? "مهام التصوير" : "قائمة مهام الفحص"}</h2>
          {can("operator", kind === "mission" ? "drone" : "inspector") && (
            <button
              className="icon-button"
              aria-label={
                kind === "mission" ? "طلب تصوير جديد" : "طلب فحص جديد"
              }
              onClick={() =>
                kind === "mission" ? newMission() : newInspection()
              }
            >
              <Plus size={21} />
            </button>
          )}
        </div>
        <label className="search-box">
          <Search size={17} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="البحث برقم المهمة أو الموقع"
            aria-label="بحث المهام"
          />
        </label>
        <select
          className="rail-filter"
          aria-label="تصفية حسب الحالة"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">جميع الحالات</option>
          {Object.keys(
            kind === "mission"
              ? {
                  new: 1,
                  scheduled: 1,
                  in_progress: 1,
                  review: 1,
                  completed: 1,
                  cancelled: 1,
                }
              : {
                  new: 1,
                  assigned: 1,
                  visited: 1,
                  result: 1,
                  closed: 1,
                  cancelled: 1,
                },
          ).map((status) => (
            <option key={status} value={status}>
              {labels[status]}
            </option>
          ))}
        </select>
        <div className="list-items">
          {filterItems(items).map((item) => (
            <button
              key={item.id}
              className={`task-item ${selectedItem?.id === item.id ? "selected" : ""}`}
              onClick={() => {
                kind === "mission"
                  ? setSelectedMission(item.id)
                  : setSelectedInspection(item.id);
                setSelectedCapture("");
              }}
            >
              <div>
                <h3>{nameOf(item.saddle_id)}</h3>
                <Badge value={item.status} />
              </div>
              <p className="mono">{idShort(item.id)}</p>
              <p>{item.reason}</p>
              <small>
                <CalendarDays size={14} />
                {fmt(item.created_at)}
              </small>
            </button>
          ))}
          {filterItems(items).length === 0 && (
            <Empty
              title="لا توجد مهام"
              detail="ستظهر الطلبات هنا بمجرد إنشائها."
            />
          )}
        </div>
      </aside>
    );
  };

  return (
    <div className="app-shell">
      <aside
        className={`sidebar ${mobileNav ? "expanded" : ""}`}
        inert={isMobile && !mobileNav}
        aria-hidden={isMobile && !mobileNav}
      >
        <Brand />
        <div className="sidebar-caption">منصة متابعة الأصول</div>
        <nav aria-label="التنقل الرئيسي">
          {pages.map(([key, label, Icon]) => (
            <button
              key={key}
              aria-label={label}
              className={page === key ? "active" : ""}
              onClick={() => goto(key)}
              aria-current={page === key ? "page" : undefined}
            >
              <Icon size={20} />
              <span>{label}</span>
              {key === "inspection" &&
                (data?.lpg_inspections || []).filter(
                  (i: RecordData) => i.status !== "closed" && i.status !== "cancelled",
                ).length > 0 && (
                  <em>
                    {
                      (data?.lpg_inspections || []).filter(
                        (i: RecordData) =>
                          i.status !== "closed" && i.status !== "cancelled",
                      ).length
                    }
                  </em>
                )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            aria-label="الإعدادات"
            onClick={() => goto("settings")}
            className={page === "settings" ? "active" : ""}
          >
            <Settings size={19} />
            <span>الإعدادات</span>
          </button>
          <div className="connection">
            <span className={`dot ${live ? "green" : "gray"}`} />
            {live ? "تحديثات النظام متصلة" : "جاري إعادة الاتصال"}
          </div>
          {page === "demo" && <small>القياسات: محاكاة / استيراد ملفات</small>}
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            onClick={() => setMobileNav(!mobileNav)}
            aria-label="فتح قائمة التنقل"
          >
            <Menu />
          </button>
          <div className="global-search">
            <Search size={20} />
            <input
              placeholder="ابحث عن منطقة أو خط أو أصل"
              value={globalSearch}
              onChange={(e) => setGlobalSearch(e.target.value)}
              aria-label="البحث العام"
            />
            {globalSearch && (
              <div className="search-results">
                {[...saddles, ...assets, ...data.pipelines]
                  .filter((a: any) => a.name.includes(globalSearch))
                  .slice(0, 8)
                  .map((a: any) => (
                    <button
                      key={a.id}
                      onClick={() => {
                        choose(a.id);
                        if (!a.id.startsWith("S-")) goto("map");
                        if (a.id.startsWith("P-")) setMapPipeline(a.id);
                        setGlobalSearch("");
                      }}
                    >
                      {a.name}
                      <ChevronLeft size={15} />
                    </button>
                  ))}
              </div>
            )}
          </div>
          <div className="account">
            <button
              className="notification-button icon-button"
              aria-label={`التنبيهات، ${activeAlerts.length} جديدة`}
              onClick={() => setNotifications(!notifications)}
            >
              <Bell size={22} />
              {activeAlerts.length > 0 && <span>{activeAlerts.length}</span>}
            </button>
            <span className="account-avatar">ع</span>
            <div>
              <strong>{user.name}</strong>
              <small>{labels[user.role]}</small>
            </div>
          </div>
        </header>
        {notifications && (
          <section className="notification-popover">
            <div className="panel-heading">
              <h3>تنبيهات النظام</h3>
              <button
                className="icon-button"
                aria-label="إغلاق التنبيهات"
                onClick={() => setNotifications(false)}
              >
                <X size={17} />
              </button>
            </div>
            {activeAlerts.length ? (
              activeAlerts.slice(0, 10).map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    choose(a.saddle_id);
                    setNotifications(false);
                  }}
                >
                  <TriangleAlert size={18} />
                  <div>
                    <strong>{a.title}</strong>
                    <small>
                      {nameOf(a.saddle_id)} · {fmt(a.created_at)}
                    </small>
                  </div>
                </button>
              ))
            ) : (
              <p>لا توجد تنبيهات جديدة.</p>
            )}
          </section>
        )}
        <main className="page-content" id="main">
          {page === "map" && (
            <>
              {shellTitle("محطات تعبئة الغاز ومناطق التوزيع ورحلات سراج الشحنة")}
              <LpgMapPage onTrip={(trip) => { setShipmentSelection(saveShipmentSelection(trip)); goto(`saddle?trip=${trip.id}`); }} />
            </>
          )}

          {page === "saddle" && (
            <>
              {shellTitle("معلومات سراج الشحنة", <label className="field"><span>سراج الشحنة</span><select aria-label="اختيار سراج الشحنة" value={shipmentSelection?.id || ''} onChange={event => {
                const trip = shipmentTrips.find(t => t.id === event.target.value);
                if (trip) { setShipmentSelection(saveShipmentSelection({...trip, viewStartedMs: Date.now()})); goto(`saddle?trip=${trip.id}`); }
              }}><option value="" disabled>اختر سراج الشحنة</option>{shipmentTrips.map(trip => <option key={trip.id} value={trip.id}>{trip.saddleId} · {trip.destination.city}</option>)}</select></label>)}
              {shipmentError ? <section className="panel" role="alert"><p>{shipmentError}</p><button onClick={() => setShipmentRetry(value => value + 1)}>إعادة المحاولة</button></section> : shipmentSelection ? <LpgSaddleDashboard key={shipmentSelection.id} trip={shipmentSelection} onBack={() => goto("map")} onCylinder={(serial, progress) => { setShipmentSelection(saveShipmentSelection({...shipmentSelection, viewProgress: progress, viewStartedMs: Date.now()})); goto(`cylinders?serial=${serial}&trip=${shipmentSelection.id}`); }} onInspection={can("operator", "inspector") ? (progress) => { setShipmentSelection(saveShipmentSelection({...shipmentSelection, viewProgress: progress, viewStartedMs: Date.now()})); goto(`inspection?trip=${shipmentSelection.id}&request=1`); } : undefined} /> : <section className="panel" role="status">جاري تجهيز أسرجة الشحنة…</section>}
            </>
          )}

          {page === "pipe-saddle" && (
            <>
              {shellTitle(
                "قراءات نقطة المراقبة وسجل الأدلة",
                <Select
                  label="السرج"
                  name="saddle"
                  defaultValue={saddle?.id}
                  onChange={(e: any) => setSelected(e.target.value)}
                >
                  {saddles.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>,
              )}
              <div className="saddle-banner">
                <div>
                  {saddle?.source && saddle.source !== "simulation" && (
                    <Badge value={saddle.source} />
                  )}
                  <h2>{saddle?.name}</h2>
                  <p>
                    <MapPin size={15} />
                    {saddle?.lat} N · {saddle?.lon} E
                  </p>
                </div>
                <div className="saddle-meta">
                  <span>
                    جودة البيانات <Badge value={saddle?.quality || "no_data"} />
                  </span>
                  <span>
                    اتصال الجهاز <strong>غير موصل</strong>
                  </span>
                  <span>
                    آخر قراءات <strong>{saddle?.last_reading_at ? fmt(saddle.last_reading_at) : episode?.saddle_id === saddle?.id ? fmt(episode.created_at) : "—"}</strong>
                  </span>
                </div>
              </div>
              <div className="readings-strip">
                {[
                  [
                    "الانفعال المحوري",
                    saddle?.latest?.strain_axial_microstrain,
                    "με",
                    "strain",
                  ],
                  [
                    "الانفعال المحيطي",
                    saddle?.latest?.strain_hoop_microstrain,
                    "με",
                    "hoop",
                  ],
                  [
                    "درجة الحرارة",
                    saddle?.latest?.temperature_k
                      ? saddle.latest.temperature_k - 273.15
                      : null,
                    "°C",
                    "temperature",
                  ],
                  [
                    "مؤشر البلل",
                    saddle?.latest?.wetness_index,
                    "0–1",
                    "wetness",
                  ],
                  ["غاز H₂S", saddle?.latest?.h2s_valid ? saddle.latest.h2s_ppm : null, "ppm", "gas"],
                ].map(([label, value, unit, metricChannel]: any) => (
                  <div key={label} className={`reading-${metricChannel}`}>
                    <MetricIcon channel={metricChannel} />
                    <span>{label}</span>
                    <strong dir="ltr">
                      {n(value, metricChannel === "gas" ? 5 : 3)} <small>{unit}</small>
                    </strong>
                  </div>
                ))}
              </div>
              <div className="saddle-columns">
                <div className="stage">
                  <Panel
                    title="سجل القراءات"
                    icon={Activity}
                    action={
                      <select
                        aria-label="قناة الرسم"
                        value={channel}
                        onChange={(e) => setChannel(e.target.value)}
                      >
                        <option value="strain">الانفعال المحوري</option>
                        <option value="hoop">الانفعال المحيطي</option>
                        <option value="temperature">الحرارة</option>
                        <option value="wetness">البلل</option>
                        <option value="gas">غاز H₂S</option>
                      </select>
                    }
                  >
                    {episode ? (
                      <>
                        <Chart episode={episode} channel={channel} />
                        <div className="chart-caption">
                          {episode.reference_rows?.length > 0 && (
                            <span>مقارنة بالقراءات المرجعية</span>
                          )}
                          <span>
                            {n(episode.assessment.valid_count, 0)} /{" "}
                            {n(episode.assessment.total_count, 0)} حزمة صالحة
                          </span>
                        </div>
                      </>
                    ) : (
                      <Empty
                        title="لا يوجد تشغيل لهذه النقطة"
                        action={
                          <button onClick={() => goto("demo")}>
                            استيراد القراءات
                          </button>
                        }
                      />
                    )}
                  </Panel>
                  <Panel title="تحليل السرج التلقائي" icon={Activity}>
                    <SaddleAI result={episode?.saddle_id === saddle?.id ? episode.assessment?.ai : saddle?.ai} />
                  </Panel>
                  <Panel title="التنبيهات والقرار" icon={Bell}>
                    {saddleAlerts.length ? (
                      saddleAlerts.map((a) => (
                        <div key={a.id} className="alert-row">
                          <TriangleAlert size={21} />
                          <div>
                            <h4>{a.title}</h4>
                            <p>{a.note}</p>
                            <small>
                              {a.basis === "trained_xgboost_416_v22" ? "نموذج السرج · XGBoost 416" : a.basis === "declared_rules_paired_control" ? "قواعد السيناريو القديم" : a.basis === "quality_rules" ? "فحص جودة القياس" : "إشارة المشغّل"} ·{" "}
                              {a.source === "simulation"
                                ? `الزمن المنقضي: ${n(a.simulation_time_s / 3600)} ساعة`
                                : fmt(a.created_at)}{" "}
                              · {idShort(a.id)}
                            </small>
                          </div>
                          <div className="alert-actions">
                            <Badge value={a.priority} />
                            {a.status === "new" &&
                              can("operator", "inspector") && (
                                <button
                                  disabled={busy}
                                  onClick={() =>
                                    run(
                                      () => api("/alerts/" + a.id + "/ack", {}),
                                      "تم تسجيل الاطلاع",
                                    )
                                  }
                                >
                                  اطلعت
                                </button>
                              )}
                            {saddleHasAlert && ["new", "acknowledged"].includes(a.status) && can("operator", "drone") && (
                              <button
                                className="primary"
                                disabled={busy}
                                onClick={() => sendDrone(a)}
                              >
                                <Plane size={14} aria-hidden="true" />
                                {sendingDrone ? "جارٍ إرسال الدرون…" : "إرسال درون"}
                              </button>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <Empty
                        title="لا توجد تنبيهات لهذا التشغيل"
                        detail="لم يُسجل تنبيه مؤكد. راجع نتائج النموذج وتوفر القنوات أعلاه."
                      />
                    )}
                    {saddleHasAlert && !saddleAlerts.some(a => ["new", "acknowledged"].includes(a.status)) && can("operator", "drone") && (
                      <button className="primary" disabled={busy} onClick={() => sendDrone()}>
                        <Plane size={14} aria-hidden="true" />
                        {sendingDrone ? "جارٍ إرسال الدرون…" : "إرسال درون"}
                      </button>
                    )}
                  </Panel>
                  <Panel
                    title="صور آخر جولة للسرج"
                    icon={ScanLine}
                    action={
                      <button
                        onClick={() => {
                          if (saddlePhotoMission)
                            setSelectedMission(saddlePhotoMission.id);
                          goto("pipe-drone");
                        }}
                      >
                        {saddlePhotoMission ? "فتح الجولة" : "جولات الدرون"}
                        <ArrowLeft size={15} />
                      </button>
                    }
                  >
                    {saddlePhotoMission && (
                      <p className="muted small gallery-context">
                        {saddlePhotoMission.asset_pack === "saddle-gallery-v33" ? (
                          <>جولة مرجعية · صور مُعدّة للعرض</>
                        ) : (
                          <>جولة {idShort(saddlePhotoMission.id)} · {fmt(saddlePhotoMission.created_at)} · {labels[saddlePhotoMission.status]}</>
                        )}
                      </p>
                    )}
                    <CapturePair
                      key={saddlePhotoMission?.id || saddle.id}
                      captures={saddlePhotos}
                      onSelect={(id) => {
                        setSelectedCapture(id);
                        setSelectedMission(saddlePhotoMission?.id || "");
                        goto("pipe-drone");
                      }}
                    />
                  </Panel>
                </div>
                <aside className="evidence-rail">
                  <section className="panel saddle-mini-panel">
                    <div className="panel-heading">
                      <h3><MapPin size={18} />موقع السرج</h3>
                      <button onClick={() => goto("map")}>الخريطة الكاملة<ArrowLeft size={14} /></button>
                    </div>
                    <SaddleMiniMap saddle={saddle} alerts={alerts} pipeline={data.pipelines?.find((p: RecordData) => p.id === saddle.pipeline_id)} />
                  </section>
                  <Panel title="سير المتابعة" icon={LinkIcon}>
                    <div className="workflow-links">
                      <button
                        onClick={() => newInspection()}
                        disabled={!can("operator", "inspector")}
                      >
                        <CheckSquare />
                        طلب فحص ميداني
                        <ChevronLeft />
                      </button>
                      <button onClick={() => goto("pipe-sources")}>
                        <FileText />
                        التقارير والمصادر
                        <ChevronLeft />
                      </button>
                      <button
                        onClick={() =>
                          run(
                            async () => {
                              const history = await api(
                                "/history/" + saddle.id,
                              );
                              setModal({ type: "history", items: history });
                            },
                            "",
                            false,
                          )
                        }
                      >
                        <History />
                        سجل التغييرات
                        <ChevronLeft />
                      </button>
                    </div>
                  </Panel>
                  <Panel title="الإصلاحات السابقة" icon={History}>
                    {sourceEvents.filter((e) => e.saddle_id === saddle.id)
                      .length ? (
                      sourceEvents
                        .filter((e) => e.saddle_id === saddle.id)
                        .map((e) => (
                          <div key={e.id} className="source-event">
                            <strong>{e.summary}</strong>
                            <p>
                              {e.event_date || "تاريخ غير موثق"} · صفحة {e.page}
                            </p>
                            <a
                              href={
                                "/api/files/" +
                                data.documents.find(
                                  (d: any) => d.id === e.document_id,
                                )?.file +
                                "#page=" +
                                e.page
                              }
                              target="_blank"
                              rel="noreferrer"
                            >
                              فتح المصدر
                            </a>
                          </div>
                        ))
                    ) : (
                      <p className="muted">
                        لم تُعتمد وقائع من تقارير سابقة لهذه النقطة.
                      </p>
                    )}
                  </Panel>
                </aside>
              </div>
            </>
          )}

          {page === "cylinders" && (
            <>
              {shellTitle("هوية الأسطوانة وتاريخ انتقالها والقراءات المرتبطة بكل رحلة")}
              <LpgCylindersPage requestedSerial={cylinderRouteSerial} contextTrip={shipmentSelection}
                onSelect={(serial) => goto(`cylinders?serial=${serial}`)}
                onSeraj={(trip) => { setShipmentSelection(saveShipmentSelection(shipmentSelection?.id === trip.id ? shipmentSelection : trip)); goto(`saddle?trip=${trip.id}`); }} />
            </>
          )}

          {page === "pipe-drone" && (
            <>
              {shellTitle(
                "طلب الجولة ومراجعة الصور وربطها بالسرج",
                can("operator", "drone") && (
                  <button className="primary" onClick={() => newMission()}>
                    <Plus size={18} />
                    طلب تصوير جديد
                  </button>
                ),
              )}
              <div className="workspace">
                <div className="stage">
                  <div className="summary-strip">
                    <div>
                      <Plane />
                      <span>طلبات تصوير</span>
                      <strong>
                        {n(
                          missions.filter((m) => m.status === "new").length,
                          0,
                        )}
                      </strong>
                    </div>
                    <div>
                      <CalendarDays />
                      <span>جولات مجدولة</span>
                      <strong>
                        {n(
                          missions.filter((m) => m.status === "scheduled")
                            .length,
                          0,
                        )}
                      </strong>
                    </div>
                    <div>
                      <Eye />
                      <span>صور بانتظار المراجعة</span>
                      <strong>
                        {n(
                          captures.filter(
                            (c) =>
                              !analyses.some(
                                (a) =>
                                  a.capture_id === c.id &&
                                  a.status === "completed",
                              ),
                          ).length,
                          0,
                        )}
                      </strong>
                    </div>
                  </div>
                  {mission ? (
                    <>
                      <section className="mission-detail panel">
                        <div className="detail-header">
                          <div>
                            <h2>{nameOf(mission.saddle_id)}</h2>
                            <span className="mono">{idShort(mission.id)}</span>
                          </div>
                          <Badge value={mission.status} />
                        </div>
                        <dl className="details-grid">
                          <div>
                            <dt>الفحص المطلوب</dt>
                            <dd>{mission.reason}</dd>
                          </div>
                          <div>
                            <dt>نوع الصور</dt>
                            <dd>{labels[mission.image_type]}</dd>
                          </div>
                          <div>
                            <dt>مشغّل الدرون</dt>
                            <dd>{mission.assignee || "لم يُعين"}</dd>
                          </div>
                          <div>
                            <dt>الموعد</dt>
                            <dd>{fmt(mission.scheduled_at)}</dd>
                          </div>
                        </dl>
                        <div className="button-row">
                          {can("drone", "operator") && (
                            <>
                              {mission.status === "new" && (
                                <button
                                  className="primary"
                                  onClick={() =>
                                    submitTransition(
                                      "missions",
                                      mission,
                                      "scheduled",
                                    )
                                  }
                                >
                                  <CalendarDays size={17} />
                                  جدولة الجولة
                                </button>
                              )}
                              {mission.status === "scheduled" && (
                                <button
                                  className="primary"
                                  onClick={() =>
                                    submitTransition(
                                      "missions",
                                      mission,
                                      "in_progress",
                                    )
                                  }
                                >
                                  <Play size={17} />
                                  بدء الجولة
                                </button>
                              )}
                              {mission.status === "in_progress" && (
                                <>
                                  <button
                                    className="primary"
                                    onClick={() =>
                                      setModal({
                                        type: "upload",
                                        item: mission,
                                      })
                                    }
                                  >
                                    <Upload size={17} />
                                    إضافة صورة
                                  </button>
                                  <button
                                    onClick={() =>
                                      submitTransition(
                                        "missions",
                                        mission,
                                        "review",
                                      )
                                    }
                                  >
                                    إرسال للمراجعة
                                  </button>
                                </>
                              )}
                              {mission.status === "review" && (
                                <>
                                  <button
                                    onClick={() =>
                                      setModal({
                                        type: "upload",
                                        item: mission,
                                      })
                                    }
                                  >
                                    <Plus size={17} />
                                    إضافة صورة
                                  </button>
                                  <button
                                    className="primary"
                                    onClick={() =>
                                      submitTransition(
                                        "missions",
                                        mission,
                                        "completed",
                                      )
                                    }
                                  >
                                    إكمال الجولة
                                  </button>
                                  <button
                                    onClick={() =>
                                      submitTransition(
                                        "missions",
                                        mission,
                                        "in_progress",
                                      )
                                    }
                                  >
                                    إعادة التصوير
                                  </button>
                                </>
                              )}
                              {["new", "scheduled", "in_progress"].includes(
                                mission.status,
                              ) && (
                                <button
                                  className="quiet danger"
                                  onClick={() =>
                                    submitTransition(
                                      "missions",
                                      mission,
                                      "cancelled",
                                    )
                                  }
                                >
                                  إلغاء الطلب
                                </button>
                              )}
                            </>
                          )}
                          <button onClick={() => choose(mission.saddle_id)}>
                            عرض سجل السرج <MapIcon size={16} />
                          </button>
                        </div>
                      </section>
                      <DroneFlightMap key={mission.id} mission={mission} saddle={saddles.find(s => s.id === mission.saddle_id)} alerts={alerts} canStart={can("operator", "drone")} onSaved={refresh} onClockSync={setFlightClockOffset} />
                      <Panel title="صور الجولة" icon={ScanLine}>
                        {arrivalPhotos.length > 0 && <ArrivalPhotos key={flightPhotoKey(mission)} captures={arrivalPhotos} />}
                        {missionCaptures.length ? (
                          <>
                            <div className="capture-tabs">
                              {missionCaptures.map((c) => (
                                <button
                                  className={
                                    capture?.id === c.id ? "active" : ""
                                  }
                                  key={c.id}
                                  onClick={() => {
                                    setSelectedCapture(c.id);
                                    setCompareCapture("");
                                  }}
                                >
                                  <img
                                    src={"/api/files/" + c.file}
                                    alt="مصغرة صورة الجولة"
                                  />
                                  <span>{labels[c.mode]}</span>
                                </button>
                              ))}
                            </div>
                            <CapturePair
                              key={mission.id}
                              captures={missionCaptures}
                              activeId={capture?.id}
                              onSelect={(id) => {
                                setSelectedCapture(id);
                                setCompareCapture("");
                              }}
                              onUpload={
                                can("operator", "drone") &&
                                ["in_progress", "review"].includes(
                                  mission.status,
                                )
                                  ? () =>
                                      setModal({
                                        type: "upload",
                                        item: mission,
                                      })
                                  : undefined
                              }
                            />
                            {previous && (
                              <div className="image-comparison previous-visit">
                                <figure>
                                  <img
                                    src={"/api/files/" + previous.file}
                                    alt="الصورة السابقة للمقارنة"
                                  />
                                  <figcaption>
                                    الزيارة السابقة · {labels[previous.mode]} ·{" "}
                                    {fmt(
                                      previous.captured_at ||
                                        previous.uploaded_at,
                                    )}
                                  </figcaption>
                                </figure>
                              </div>
                            )}
                            <p className="selected-evidence">
                              الصورة المختارة للمراجعة والتحليل:{" "}
                              <strong>{labels[capture.mode]}</strong> ·{" "}
                              {idShort(capture.id)}
                            </p>
                            <div className="capture-tools">
                              <label>
                                المقارنة بزيارة سابقة
                                <select
                                  aria-label="صورة الزيارة السابقة"
                                  value={compareCapture}
                                  onChange={(e) =>
                                    setCompareCapture(e.target.value)
                                  }
                                >
                                  <option value="">بدون مقارنة</option>
                                  {captures
                                    .filter(
                                      (c) =>
                                        c.saddle_id === capture.saddle_id &&
                                        c.id !== capture.id &&
                                        c.mission_id !== capture.mission_id &&
                                        c.mode === capture.mode,
                                    )
                                    .map((c) => (
                                      <option key={c.id} value={c.id}>
                                        {idShort(c.id)} · {fmt(c.uploaded_at)}
                                      </option>
                                    ))}
                                </select>
                              </label>
                              {can("operator", "drone", "inspector") && (
                                <button
                                  disabled={busy || (!data.config.gemini_ready && !savedAvailable)}
                                  className="primary"
                                  onClick={() =>
                                    run(async () => {
                                      const a = await api(
                                        "/captures/" + capture.id + "/analyze",
                                        { previous_id: compareCapture || null },
                                      );
                                      if (a.status === "failed")
                                        throw new Error(a.error);
                                      return a;
                                    }, (a) => a.execution_mode === "cached" ? "تعذر التحليل الحي؛ عُرض تحليل محفوظ للصورة نفسها" : "اكتمل تحليل Gemini الحي")
                                  }
                                >
                                  تحليل الصورة
                                </button>
                              )}
                              {can("operator", "drone", "inspector") && data.config.visual_cache_fallback_enabled && (
                                <button
                                  disabled={busy || !savedAvailable}
                                  onClick={() => run(async () => {
                                    const a = await api("/captures/" + capture.id + "/analyze", {
                                      previous_id: compareCapture || null, strategy: "saved",
                                    });
                                    if (a.status === "failed") throw new Error(a.error);
                                    return a;
                                  }, "عُرض التحليل المحفوظ؛ لم يُرسل طلب إلى Gemini")}
                                >
                                  <History size={17} /> عرض التحليل المحفوظ
                                </button>
                              )}
                              {can("operator", "inspector") && (
                                <button
                                  onClick={() =>
                                    setModal({ type: "review", item: capture })
                                  }
                                >
                                  تسجيل مراجعة بشرية
                                </button>
                              )}
                              {capture.mode === "thermal" &&
                                can("operator", "drone") && (
                                  <button
                                    onClick={() =>
                                      setModal({
                                        type: "thermal",
                                        item: capture,
                                      })
                                    }
                                  >
                                    إضافة مصفوفة حرارة
                                  </button>
                                )}
                            </div>
                            {!data.config.gemini_ready && (
                              <p className="inline-note">
                                التحليل الحي ينتظر مفتاح Gemini. {savedAvailable ? "يتوفر تحليل محفوظ مطابق للصورة المختارة." : "لا يوجد تحليل محفوظ مطابق؛ المراجعة البشرية متاحة."}
                              </p>
                            )}
                            {data.config.gemini_ready && data.config.visual_cache_fallback_enabled && (
                              <p className="inline-note">
                                {savedAvailable ? "يتوفر تحليل محفوظ لهذه الصورة والمقارنة، ويُستخدم إذا تعذر التحليل الحي." : "عند نجاح التحليل الحي، تُحفظ نتيجته لاستخدامها إذا تعذر الاتصال أثناء العرض."}
                              </p>
                            )}
                            {capture.mode === "thermal" && (
                              <div className="thermal-note">
                                {capture.thermal ? (
                                  <>
                                    <strong>
                                      Tmax: {n(capture.thermal.tmax_c)} °C · ΔT:{" "}
                                      {n(capture.thermal.delta_c)} °C
                                    </strong>
                                    <p>{capture.thermal.note}</p>
                                  </>
                                ) : (
                                  <p>
                                    صورة حرارية نوعية؛ لا تتوفر درجات حرارة
                                    رقمية قبل استيراد مصفوفة موثقة.
                                  </p>
                                )}
                              </div>
                            )}
                            {captureAnalyses.map((a) => (
                              <div key={a.id} className="analysis-result">
                                {a.status !== "completed" ? (
                                  <p className="red-text">
                                    <TriangleAlert size={17} />
                                    {a.status === "failed" ? a.error : "جارٍ تحليل الصورة…"}
                                  </p>
                                ) : (
                                  <>
                                    <div className="detail-header">
                                      <h4>
                                        {labels[a.provider]} ·{" "}
                                        {a.result.summary}
                                      </h4>
                                      <Badge value={a.status} />
                                    </div>
                                    {a.provider === "gemini" && (
                                      <p className="inline-note" role="status">
                                        <strong>{a.execution_mode === "cached" ? "تحليل Gemini محفوظ" : "تحليل Gemini حي"}</strong>
                                        {a.execution_profile?.transport === "antigravity" && <> · عبر Antigravity</>}
                                        {a.execution_mode === "cached" ? <> · أُجري {fmt(a.original_analyzed_at)} · لم يُجرَ تحليل حي لهذا الطلب.</> : <> · {fmt(a.created_at)}</>}
                                        {a.execution_mode === "cached" && a.fallback_reason !== "operator_selected_saved" && <> تعذر الاتصال أو الوصول إلى المزود.</>}
                                      </p>
                                    )}
                                    {a.result.findings.map(
                                      (f: any, i: number) => (
                                        <div className="finding" key={i}>
                                          <Badge value={f.category} />
                                          <p>
                                            <b>المشاهدة:</b> {f.observation}
                                          </p>
                                          <p>
                                            <b>تفسير محتمل:</b>{" "}
                                            {f.interpretation}
                                          </p>
                                        </div>
                                      ),
                                    )}
                                    <p>
                                      <b>الإجراء:</b> {a.result.next_action}
                                    </p>
                                    <small>
                                      {a.result.limitations.join(" · ")}
                                    </small>
                                  </>
                                )}
                              </div>
                            ))}
                            <div className="button-row">
                              <button
                                disabled={busy}
                                onClick={() =>
                                  run(async () => {
                                    await api(
                                      "/missions/" + mission.id + "/report",
                                      {},
                                    );
                                  }, "تم إنشاء مسودة التقرير")
                                }
                              >
                                إنشاء تقرير <FileText size={17} />
                              </button>
                              {reports
                                .filter((r) => r.mission_id === mission.id)
                                .map((r) => (
                                  <a
                                    key={r.id}
                                    className="button-link"
                                    href={"/api/reports/" + r.id + "/print"}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    فتح التقرير <Eye size={16} />
                                  </a>
                                ))}
                            </div>
                          </>
                        ) : arrivalPhotos.length === 0 ? (
                          <CapturePair
                            key={mission.id}
                            captures={[]}
                            onUpload={
                              can("operator", "drone") &&
                              ["in_progress", "review"].includes(mission.status)
                                ? () =>
                                    setModal({ type: "upload", item: mission })
                                : undefined
                            }
                          />
                        ) : null}
                      </Panel>
                    </>
                  ) : (
                    <Empty
                      title="ابدأ بطلب تصوير"
                      detail="يمكن إنشاء الطلب من تنبيه السرج أو يدويًا لملاحظة ميدانية."
                      action={
                        <button
                          className="primary"
                          onClick={() => newMission()}
                        >
                          طلب تصوير جديد
                        </button>
                      }
                    />
                  )}
                </div>
                {taskRail("mission")}
              </div>
            </>
          )}

          {page === "inspection" && (
            <>
              {shellTitle("طلبات فحص سروج الشحنات ونتائج تقييمها")}
              <LpgInspectionsPage
                requestedTask={new URLSearchParams(routeHash.split('?')[1]).get('task')}
                requestedTrip={shipmentRouteId}
                requestNew={new URLSearchParams(routeHash.split('?')[1]).get('request') === '1'}
                contextTrip={shipmentSelection}
                canRequest={can("operator", "inspector")} canEvaluate={can("inspector")}
                onSelect={(id) => goto(`inspection?task=${id}`)}
                onSeraj={(trip) => { setShipmentSelection(saveShipmentSelection(shipmentSelection?.id === trip.id ? shipmentSelection : trip)); goto(`saddle?trip=${trip.id}`); }}
                onChanged={refresh} />
            </>
          )}

          {page === "pipe-inspection" && (
            <>
              {shellTitle(
                "الفحص الميداني ونتيجته وقرار الإغلاق",
                can("operator", "inspector") && (
                  <button className="primary" onClick={() => newInspection()}>
                    <Plus size={18} />
                    طلب فحص جديد
                  </button>
                ),
              )}
              <div className="workspace">
                <div className="stage">
                  <div className="summary-strip">
                    <div>
                      <ClipboardList />
                      <span>طلبات جديدة</span>
                      <strong>
                        {n(
                          inspections.filter((i) => i.status === "new").length,
                          0,
                        )}
                      </strong>
                    </div>
                    <div>
                      <Clock />
                      <span>قيد التنفيذ</span>
                      <strong>
                        {n(
                          inspections.filter((i) =>
                            ["assigned", "visited", "result"].includes(
                              i.status,
                            ),
                          ).length,
                          0,
                        )}
                      </strong>
                    </div>
                    <div>
                      <CircleCheck />
                      <span>مغلقة</span>
                      <strong>
                        {n(
                          inspections.filter((i) => i.status === "closed")
                            .length,
                          0,
                        )}
                      </strong>
                    </div>
                  </div>
                  {inspection ? (
                    <>
                      <section className="panel mission-detail">
                        <div className="detail-header">
                          <div>
                            <h2>{nameOf(inspection.saddle_id)}</h2>
                            <span className="mono">
                              {idShort(inspection.id)}
                            </span>
                          </div>
                          <Badge value={inspection.status} />
                        </div>
                        <dl className="details-grid">
                          <div>
                            <dt>الفحص المطلوب</dt>
                            <dd>{inspection.reason}</dd>
                          </div>
                          <div>
                            <dt>المفتش</dt>
                            <dd>{inspection.assignee || "بانتظار التعيين"}</dd>
                          </div>
                          <div>
                            <dt>الإنشاء</dt>
                            <dd>{fmt(inspection.created_at)}</dd>
                          </div>
                          <div>
                            <dt>الموعد</dt>
                            <dd>{fmt(inspection.scheduled_at)}</dd>
                          </div>
                        </dl>
                      </section>
                      <Panel title="سير مهمة الفحص" icon={LinkIcon}>
                        <ol className="progress-track">
                          {[
                            "new",
                            "assigned",
                            "visited",
                            "result",
                            "closed",
                          ].map((status, index) => (
                            <li
                              key={status}
                              className={
                                index <=
                                [
                                  "new",
                                  "assigned",
                                  "visited",
                                  "result",
                                  "closed",
                                ].indexOf(inspection.status)
                                  ? "done"
                                  : ""
                              }
                            >
                              <span />
                              <strong>{labels[status]}</strong>
                            </li>
                          ))}
                        </ol>
                        <div className="button-row">
                          {can("inspector") && (
                            <>
                              {inspection.status === "new" && (
                                <button
                                  className="primary"
                                  onClick={() =>
                                    submitTransition(
                                      "inspections",
                                      inspection,
                                      "assigned",
                                    )
                                  }
                                >
                                  <UserRound size={17} />
                                  تعيين مفتش
                                </button>
                              )}
                              {inspection.status === "assigned" && (
                                <button
                                  className="primary"
                                  onClick={() =>
                                    submitTransition(
                                      "inspections",
                                      inspection,
                                      "visited",
                                    )
                                  }
                                >
                                  تسجيل زيارة الموقع
                                </button>
                              )}
                              {inspection.status === "visited" && (
                                <button
                                  className="primary"
                                  onClick={() =>
                                    submitTransition(
                                      "inspections",
                                      inspection,
                                      "result",
                                    )
                                  }
                                >
                                  تسجيل نتيجة الفحص
                                </button>
                              )}
                              {inspection.status === "result" && (
                                <>
                                  <button
                                    className="primary"
                                    onClick={() =>
                                      submitTransition(
                                        "inspections",
                                        inspection,
                                        "closed",
                                      )
                                    }
                                  >
                                    اعتماد القرار والإغلاق
                                  </button>
                                  <button
                                    onClick={() =>
                                      submitTransition(
                                        "inspections",
                                        inspection,
                                        "visited",
                                      )
                                    }
                                  >
                                    إعادة الفحص
                                  </button>
                                </>
                              )}
                              {["new", "assigned"].includes(
                                inspection.status,
                              ) && (
                                <button
                                  className="quiet danger"
                                  onClick={() =>
                                    submitTransition(
                                      "inspections",
                                      inspection,
                                      "cancelled",
                                    )
                                  }
                                >
                                  إلغاء الطلب
                                </button>
                              )}
                            </>
                          )}
                          <button onClick={() => choose(inspection.saddle_id)}>
                            فتح سجل السرج <MapIcon size={17} />
                          </button>
                        </div>
                      </Panel>
                      <div className="two-columns">
                        <Panel title="نتيجة الفحص وقياسات NDT" icon={Activity}>
                          {inspection.result ? (
                            <>
                              <p>{inspection.result}</p>
                              <p>
                                <b>NDT:</b>{" "}
                                {inspection.ndt || "لم تسجل قياسات NDT"}
                              </p>
                            </>
                          ) : (
                            <Empty
                              title="لم تسجل نتيجة بعد"
                              detail="تُضاف النتائج بعد زيارة المفتش للموقع."
                            />
                          )}
                        </Panel>
                        <Panel title="التقرير والقرار" icon={FileText}>
                          {inspection.report_id && (
                            <a
                              className="button-link"
                              target="_blank"
                              rel="noreferrer"
                              href={
                                "/api/reports/" +
                                inspection.report_id +
                                "/print"
                              }
                            >
                              فتح التقرير المرتبط <Eye size={16} />
                            </a>
                          )}
                          <p>{inspection.notes || "بانتظار قرار المفتش"}</p>
                        </Panel>
                      </div>
                    </>
                  ) : (
                    <Empty
                      title="لا توجد مهام فحص"
                      detail="بعد مراجعة الصور، أنشئ مهمة واربطها بالتقرير."
                      action={
                        <button
                          className="primary"
                          onClick={() => newInspection()}
                        >
                          طلب فحص جديد
                        </button>
                      }
                    />
                  )}
                </div>
                {taskRail("inspection")}
              </div>
            </>
          )}

          {page === "sources" && <>
            {shellTitle("تقرير الأسطوانة المختصر للعميل · البحث بالرقم التسلسلي والتصدير")}
            <LpgCustomerReport requestedSerial={cylinderRouteSerial || (() => { try { return sessionStorage.getItem('qaif.lpg.last-cylinder'); } catch { return null; } })() || 'CYL-001-01'}
              onSelect={serial => goto(`sources?serial=${encodeURIComponent(serial)}`)} />
          </>}

          {page === "pipe-sources" && (
            <>
              {shellTitle(
                "تقارير الزيارات والمراجع المعتمدة",
                <button
                  className="primary"
                  disabled={!can("operator", "inspector")}
                  onClick={() => setModal({ type: "document" })}
                >
                  <Upload size={18} />
                  استيراد تقرير سابق
                </button>,
              )}
              <div className="sources-layout">
                <div className="stage">
                  <Panel title="تقارير جولات الدرون" icon={FileText}>
                    {reports.length ? (
                      <div className="report-table">
                        {reports.map((r) => (
                          <div className="report-row" key={r.id}>
                            <FileText size={25} />
                            <div>
                              <strong>{nameOf(r.saddle_id)}</strong>
                              <small>
                                {idShort(r.id)} · {fmt(r.created_at)}
                              </small>
                            </div>
                            <Badge value={r.status} />
                            <a
                              className="button-link"
                              target="_blank"
                              rel="noreferrer"
                              href={"/api/reports/" + r.id + "/print"}
                            >
                              عرض / PDF <Eye size={15} />
                            </a>
                            <a
                              className="button-link"
                              href={"/api/reports/" + r.id + "/json"}
                            >
                              JSON <Download size={15} />
                            </a>
                            <button
                              disabled={!can("operator", "inspector")}
                              onClick={() => newInspection(r.saddle_id, r.id)}
                            >
                              طلب فحص
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <Empty
                        title="لا توجد تقارير بعد"
                        detail="تُنشأ مسودة التقرير من مراجعة صور الجولة."
                      />
                    )}
                  </Panel>
                  <Panel title="الوقائع المستخرجة والمعتمدة" icon={History}>
                    {sourceEvents.length ? (
                      sourceEvents.map((e) => (
                        <div className="document-event" key={e.id}>
                          <div className="detail-header">
                            <strong>{e.summary}</strong>
                            <Badge value="approved" />
                          </div>
                          <blockquote>{e.quote}</blockquote>
                          <small>
                            {nameOf(e.saddle_id)} ·{" "}
                            {e.event_date || "تاريخ غير موثق"} · صفحة {e.page} ·
                            اعتمدها {e.approved_by}
                          </small>
                        </div>
                      ))
                    ) : (
                      <Empty
                        title="لم تُعتمد وقائع بعد"
                        detail="استورد PDF ثم راجع النص وحدد صفحته قبل إضافته إلى سجل السرج."
                      />
                    )}
                  </Panel>
                </div>
                <aside className="evidence-rail">
                  <Panel title="المراجع السابقة" icon={LinkIcon}>
                    {data.documents.length ? (
                      data.documents.map((d: any) => (
                        <div key={d.id} className="source-document">
                          <strong>{d.name}</strong>
                          <small>
                            {nameOf(d.saddle_id)} · {d.pages.length} صفحة
                          </small>
                          <p>{d.note}</p>
                          <div className="button-row">
                            <a
                              className="button-link"
                              target="_blank"
                              rel="noreferrer"
                              href={"/api/files/" + d.file}
                            >
                              فتح PDF
                            </a>
                            <button
                              onClick={() =>
                                setModal({ type: "sourceEvent", item: d })
                              }
                            >
                              مراجعة النص
                            </button>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="muted">
                        أضف تقرير PDF لربط سوابق الأصل بمصدرها.
                      </p>
                    )}
                  </Panel>
                  <Panel title="اقتراح أولوية تركيب السروج" icon={Radio}>
                    <p className="muted small">
                      لحام +3، بلل +2، إصلاح سابق +4. اقتراح قواعد يحتاج
                      اعتمادًا هندسيًا.
                    </p>
                    <button
                      onClick={() =>
                        run(
                          async () => {
                            const recommendations = await api("/placements");
                            setModal({
                              type: "placements",
                              items: recommendations,
                            });
                          },
                          "",
                          false,
                        )
                      }
                    >
                      عرض الاقتراحات <ArrowLeft size={16} />
                    </button>
                    {data.placements.map((p: any) => (
                      <div className="source-event" key={p.id}>
                        <strong>{nameOf(p.saddle_id)}</strong>
                        <Badge value={p.decision} />
                        <p>{p.notes}</p>
                      </div>
                    ))}
                  </Panel>
                </aside>
              </div>
            </>
          )}

          {page === "demo" && (
            <>
              {shellTitle(
                "إعادة تشغيل بيانات المحاكي والتحقق من التنبيهات",
                <Badge value="simulation">وضع بحثي</Badge>,
              )}
              <div className="demo-layout">
                <Panel title="تشغيل حالة محفوظة" icon={Play}>
                  <p>
                    تُقرأ القياسات الرقمية فقط. حالات النموذج تستخدم الحزمة المعتمدة تلقائيًا؛ السيناريوهات القديمة تحتفظ بقواعد المقارنة.
                  </p>
                  <form
                    onSubmit={(e) => {
                      const values = form(e);
                      run(
                        () =>
                          api(
                            values.playback === "stream"
                              ? "/demo/stream"
                              : "/demo/replay",
                            values,
                          ),
                        values.playback === "stream"
                          ? "بدأ التشغيل المتدرج؛ تابع القراءات في سجل السرج"
                          : "اكتملت إعادة التشغيل؛ القراءات والتنبيهات محفوظة",
                      );
                    }}
                  >
                    <Select
                      label="نقطة المراقبة"
                      name="saddle_id"
                      defaultValue={saddle?.id}
                    >
                      {saddles.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </Select>
                    <Select
                      label="حالة التشغيل"
                      name="case"
                      defaultValue="ai_reference"
                    >
                      <option value="ai_reference">AI · تشغيل مرجعي</option>
                      <option value="ai_quality_control">AI · مرجع مع اضطراب جودة القياس</option>
                      <option value="ai_crack">AI · استجابة شقوق</option>
                      <option value="ai_thermal">AI · شذوذ حراري</option>
                      <option value="ai_wetness">AI · بلل ومراجعة الطلاء</option>
                      <option value="ai_h2s">AI · استجابة H₂S</option>
                      <option value="control">تشغيل مرجعي بدون تدخل</option>
                      <option value="early_bending">
                        تغير ميكانيكي في الانفعال
                      </option>
                      <option value="early_wet_path">مسار بلل</option>
                      <option value="early_coupling">تغير اقتران السرج</option>
                      <option value="early_packet_gap">انقطاع الحزم</option>
                      <option value="early_temperature_flatline">
                        ثبات حساس الحرارة
                      </option>
                    </Select>
                    <Select
                      label="طريقة العرض"
                      name="playback"
                      defaultValue="instant"
                    >
                      <option value="instant">استيراد التشغيل كاملًا</option>
                      <option value="stream">
                        تشغيل متدرج مسرّع للتصوير
                      </option>
                    </Select>
                    <button
                      disabled={busy || !can("operator")}
                      className="primary"
                    >
                      <Play size={18} />
                      {busy ? "جاري التشغيل…" : "إعادة التشغيل"}
                    </button>
                  </form>
                  <p className="inline-note">
                    حزمة XGBoost 416 مفعلة. حالات AI مدتها 20 دقيقة بقراءة كل 5 ثوانٍ، وتبدأ بـ120 ثانية تهيئة سليمة. الحالات القديمة مدتها 72 ساعة ويظل تحليلها بالقواعد منفصلًا.
                  </p>
                </Panel>
                <Panel title="استيراد قراءات من ملف" icon={Upload}>
                  <p>
                    يمكن استيراد تصدير الجهاز أو المحاكي بصيغة CSV. يبدأ النموذج تلقائيًا بعد تهيئة سليمة معلومة، مع قراءات كل 5 ثوانٍ تقريبًا.
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const f = new FormData(e.currentTarget);
                      run(async () => {
                        const file = f.get("file") as File;
                        const rows = (await file.text()).trim().split(/\r?\n/);
                        const headers = rows.shift()!.split(",");
                        const values = rows.map((line) =>
                          Object.fromEntries(
                            line
                              .split(",")
                              .map((v, i) => [
                                headers[i],
                                ["packet_valid", "h2s_valid"].includes(headers[i])
                                  ? v.toLowerCase() === "true"
                                  : headers[i] === "h2s_status" ? v
                                  : v
                                    ? Number(v)
                                    : null,
                              ]),
                          ),
                        );
                        return api(
                          "/saddles/" + f.get("saddle_id") + "/readings",
                          { rows: values, source: "imported", baseline_verified: f.get("baseline_verified") === "on" },
                        );
                      }, "تم استيراد القراءات");
                    }}
                  >
                    <Select
                      label="نقطة المراقبة"
                      name="saddle_id"
                      defaultValue={saddle?.id}
                    >
                      {saddles.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </Select>
                    <Field label="ملف observed.csv" name="file" type="file" />
                    <label className="ai-baseline-check"><input name="baseline_verified" type="checkbox" />أؤكد أن أول 120 ثانية تمثل تهيئة سليمة معلومة لهذا السرج</label>
                    <button disabled={busy || !can("operator")}>استيراد</button>
                  </form>
                  <small className="mono">
                    timestamp_s, strain_hoop_microstrain,
                    strain_axial_microstrain, temperature_k, wetness_index,
                    packet_valid, h2s_ppm, h2s_valid, h2s_status
                  </small>
                </Panel>
                <Panel title="محاكاة إشارة السرج للفيديو" icon={Radio}>
                  <p>
                    عند تجهيز عرض الكاميرا، يمكن بدء الرحلة بإشارة اختبار واضحة
                    المصدر. هذه الإشارة يختارها المشغّل ولا تستنتجها قواعد
                    المحاكي.
                  </p>
                  <form
                    onSubmit={(e) => {
                      const values = form(e);
                      run(async () => {
                        const a = await api("/demo/signal", values);
                        setSelected(a.saddle_id);
                        goto("pipe-saddle");
                      }, "حُفظت إشارة الاختبار مع مصدرها");
                    }}
                  >
                    <Select
                      label="نقطة الإشارة"
                      name="saddle_id"
                      defaultValue={saddle?.id}
                    >
                      {saddles.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </Select>
                    <Select
                      label="مسار الإشارة"
                      name="category"
                      defaultValue="thermal"
                    >
                      <option value="thermal">حراري — سيناريو الفيديو</option>
                      <option value="mechanical">انفعال</option>
                      <option value="wetness">بلل وطلاء</option>
                    </Select>
                    <button disabled={busy || !can("operator")}>
                      إرسال إشارة اختبار
                    </button>
                  </form>
                </Panel>
                <Panel title="التشغيلات المحفوظة" icon={History}>
                  {data.episodes.map((e: any) => (
                    <div className="episode-row" key={e.id}>
                      <div>
                        <strong>{nameOf(e.saddle_id)}</strong>
                        <small>
                          {e.case} · {fmt(e.created_at)}{" "}
                          {e.playback_status === "running"
                            ? ` · جارٍ ${e.progress}%`
                            : ""}
                        </small>
                      </div>
                      {e.playback_status === "running" && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(
                              () => api("/demo/stop/" + e.saddle_id, {}),
                              "توقف التشغيل مع حفظ القراءات",
                            )
                          }
                        >
                          إيقاف التشغيل
                        </button>
                      )}
                      <Badge value={e.source} />
                      <button
                        onClick={() =>
                          run(
                            async () => {
                              setEpisode(await api("/episodes/" + e.id));
                              setModal({
                                type: "episode",
                                item: await api("/episodes/" + e.id),
                              });
                            },
                            "",
                            false,
                          )
                        }
                      >
                        عرض نتيجة التحليل
                      </button>
                    </div>
                  ))}
                </Panel>
              </div>
            </>
          )}

          {page === "settings" && (
            <>
              {shellTitle("الأدوار واتصال التحليل والكاميرا")}
              <div className="two-columns">
                <Panel title="اتصال تحليل الصور" icon={ScanLine}>
                  <Badge value={data.config.gemini_ready ? "good" : "no_data"}>
                    {data.config.gemini_ready
                      ? "المفتاح مضبوط؛ يلزم اختبار صورة"
                      : "ينتظر مفتاح Gemini"}
                  </Badge>
                  <p>
                    اسم النموذج:{" "}
                    <span className="mono">{data.config.gemini_model}</span>
                    {data.config.gemini_transport === "antigravity" && <> · عبر Antigravity</>}
                  </p>
                  <p>
                    أضف GEMINI_API_KEY إلى ملف .env في مجلد المشروع ثم أعد تشغيل
                    الخادم. لا تضع المفتاح في الواجهة أو المحادثة.
                  </p>
                  <p className="muted">
                    الصور تُرسل إلى المزود عند الضغط على «تحليل الصورة» فقط. «عرض التحليل المحفوظ» لا يرسل طلبًا خارجيًا.
                  </p>
                  <p>
                    نتائج محفوظة: {n(data.config.saved_visual_results, 0)} · {data.config.visual_cache_fallback_enabled ? "البديل المحفوظ متاح في وضع العرض" : "البديل المحفوظ معطل خارج وضع العرض"}.
                  </p>
                  <p className="muted">
                    حدود الخطة المجانية تُراجع في Google AI Studio؛ وجود المفتاح لا يؤكد الحصة المتاحة.
                  </p>
                </Panel>
                <Panel title="الكاميرا الحرارية" icon={Thermometer}>
                  <Badge value="no_data">لم تُختبر الكاميرا بعد</Badge>
                  <p>
                    رفع الصور وتصدير ملفات الكاميرا متاح. استقبال بث مباشر يحتاج
                    معرفة نوع الكاميرا وواجهة اتصالها.
                  </p>
                  <p>
                    الألوان الحرارية تُراجع نوعيًا؛ القياسات الرقمية تتطلب
                    مصفوفة درجات حرارة ومراجعة معايرتها.
                  </p>
                </Panel>
                <Panel title="المستخدم والصلاحيات" icon={UserRound}>
                  <p>
                    {user.name} · {labels[user.role]}
                  </p>
                  {data.config.demo_login_enabled && (
                    <div className="button-row">
                      {["admin", "operator", "drone", "inspector"].map(
                        (role) => (
                          <button
                            key={role}
                            disabled={busy || role === user.role}
                            onClick={() =>
                              run(async () => {
                                setUser(
                                  await api("/auth/demo?role=" + role, {}),
                                );
                              }, "تم تغيير دور العرض")
                            }
                          >
                            {labels[role]}
                          </button>
                        ),
                      )}
                    </div>
                  )}
                  {user.role === "admin" && (
                    <button onClick={() => setModal({ type: "user" })}>
                      إضافة مستخدم
                    </button>
                  )}
                  <button
                    className="quiet"
                    onClick={() =>
                      run(async () => {
                        await api("/auth/logout", {});
                        setUser(null);
                        setData(null);
                      }, "تم تسجيل الخروج")
                    }
                  >
                    <LogOut size={16} />
                    تسجيل الخروج
                  </button>
                </Panel>
                <Panel title="حدود النسخة الحالية" icon={ShieldCheck}>
                  <p>
                    نتائج القواعد والمراجعة البصرية تحتاج اعتماد مفتش؛ لا تدعي
                    النسخة قياس عمق الشق أو إثبات تسرب.
                  </p>
                  <p>
                    مصدر الخريطة: Natural Earth، بيانات المجال العام. تعمل
                    الخريطة والخطوط محليًا دون خدمة خرائط خارجية.
                  </p>
                </Panel>
              </div>
            </>
          )}
        </main>
        <footer className="app-footer">
          <span>قائف · سجل واضح لكل إشارة وقرار</span>
          {page === "demo" && (
            <span>
              نسخة التطوير 0.1 ·{" "}
              {data.config.demo_mode ? "وضع العرض المحلي" : "وضع المستخدمين"}
            </span>
          )}
        </footer>
      </div>

      {modal && (
        <Modal
          title={
            modal.type === "mission"
              ? "طلب تصوير جديد"
              : modal.type === "inspection"
                ? "طلب فحص جديد"
                : modal.type === "transition"
                  ? labels[modal.target]
                  : modal.type === "upload"
                    ? "إضافة صورة الجولة"
                    : modal.type === "review"
                      ? "مراجعة بشرية للصورة"
                      : modal.type === "thermal"
                        ? "استيراد درجات الحرارة"
                        : modal.type === "document"
                          ? "استيراد تقرير سابق"
                          : modal.type === "sourceEvent"
                            ? "مراجعة نص التقرير"
                            : modal.type === "user"
                              ? "إضافة مستخدم"
                              : "سجل الأدلة"
          }
          close={() => setModal(null)}
        >
          {["mission", "inspection"].includes(modal.type) && (
            <form
              onSubmit={(e) => {
                const values = form(e);
                run(async () => {
                  const result = await api(
                    modal.type === "mission" ? "/missions" : "/inspections",
                    {
                      ...values,
                      alert_id: modal.alertId || null,
                      report_id: modal.reportId || null,
                    },
                  );
                  if (modal.type === "mission") {
                    setSelectedMission(result.id);
                    goto("pipe-drone");
                  } else {
                    setSelectedInspection(result.id);
                    goto("pipe-inspection");
                  }
                }, "تم إنشاء الطلب");
              }}
            >
              <Select
                label="نقطة المراقبة"
                name="saddle_id"
                defaultValue={modal.saddleId}
              >
                {saddles.map((s) => (
                  <option value={s.id} key={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
              {modal.type === "mission" && (
                <Select
                  label="نوع الصور المطلوبة"
                  name="image_type"
                  defaultValue="both"
                >
                  <option value="both">عادية وحرارية</option>
                  <option value="rgb">عادية RGB</option>
                  <option value="thermal">حرارية</option>
                </Select>
              )}
              <Field
                label={
                  modal.type === "mission" ? "سبب طلب التصوير" : "الفحص المطلوب"
                }
                name="reason"
                area
                defaultValue={
                  modal.alertId
                    ? alerts.find((a) => a.id === modal.alertId)?.title
                    : ""
                }
              />
              <button className="primary" disabled={busy}>
                إنشاء الطلب
              </button>
            </form>
          )}
          {modal.type === "transition" && (
            <form
              onSubmit={(e) => {
                const values = form(e);
                run(
                  () =>
                    api(
                      "/" + modal.kind + "/" + modal.item.id + "/transition",
                      { ...values, status: modal.target },
                    ),
                  "تم تحديث حالة المهمة",
                );
              }}
            >
              {["scheduled", "assigned"].includes(modal.target) && (
                <>
                  <Field
                    label={
                      modal.kind === "missions" ? "مشغل الدرون" : "اسم المفتش"
                    }
                    name="assignee"
                    defaultValue={modal.item.assignee || user.name}
                  />
                  <Field
                    label="الموعد"
                    name="scheduled_at"
                    type="datetime-local"
                    required={modal.target === "scheduled"}
                  />
                </>
              )}
              {modal.target === "result" && (
                <>
                  <Field label="نتيجة الفحص" name="result" area />
                  <Field
                    label="قياسات NDT وملاحظات الجهاز"
                    name="ndt"
                    area
                    required={false}
                  />
                </>
              )}
              <Field
                label={
                  modal.target === "closed"
                    ? "القرار ومبرر الإغلاق"
                    : "ملاحظات الإجراء"
                }
                name="notes"
                area
                required={["closed", "cancelled"].includes(modal.target)}
              />
              <p className="muted small">
                سيُحفظ الإجراء واسم المستخدم في سجل المهمة.
              </p>
              <button className="primary" disabled={busy}>
                حفظ
              </button>
            </form>
          )}
          {modal.type === "upload" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const values = new FormData(e.currentTarget);
                run(
                  () => api("/missions/" + modal.item.id + "/captures", values),
                  "تم رفع الصورة",
                );
              }}
            >
              <Field
                label="الصورة (JPG / PNG / WEBP، حتى 10 MB)"
                name="file"
                type="file"
              />
              <Select label="نوع الصورة" name="mode" defaultValue="rgb">
                <option value="rgb">عادية RGB</option>
                <option value="thermal">حرارية</option>
              </Select>
              <Select label="مصدرها" name="source" defaultValue="uploaded">
                <option value="uploaded">صورة مرفوعة</option>
                <option value="camera_export">تصدير من الكاميرا</option>
                <option value="prepared_demo">صورة معدة للعرض</option>
              </Select>
              <Field
                label="وقت التصوير إن كان موثقًا"
                name="captured_at"
                type="datetime-local"
                required={false}
              />
              <Field label="وصف الصورة" name="note" area required={false} />
              <button className="primary" disabled={busy}>
                رفع الصورة
              </button>
            </form>
          )}
          {modal.type === "review" && (
            <form
              onSubmit={(e) => {
                const values = form(e);
                run(
                  () => api("/captures/" + modal.item.id + "/review", values),
                  "حُفظت المراجعة البشرية",
                );
              }}
            >
              <Field label="ملخص المراجعة" name="summary" />
              <Field label="ما يظهر في الصورة" name="observation" area />
              <Select
                label="تصنيف المشاهدة"
                name="category"
                defaultValue="crack_like"
              >
                {[
                  "crack_like",
                  "coating",
                  "corrosion_like",
                  "thermal",
                  "other",
                  "none",
                ].map((k) => (
                  <option key={k} value={k}>
                    {labels[k]}
                  </option>
                ))}
              </Select>
              <Field
                label="التفسير المحتمل وحدوده"
                name="interpretation"
                area
              />
              <Field label="الإجراء المقترح" name="next_action" area />
              <button className="primary" disabled={busy}>
                حفظ المراجعة
              </button>
            </form>
          )}
          {modal.type === "thermal" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  () =>
                    api(
                      "/captures/" + modal.item.id + "/thermal",
                      new FormData(e.currentTarget),
                    ),
                  "حُفظت القيم الحرارية",
                );
              }}
            >
              <p>
                مصفوفة NPY ثنائية الأبعاد من تصدير الكاميرا. حدّد منطقة الأنبوب
                بإحداثيات نسبية x0,y0,x1,y1 بين 0 و1.
              </p>
              <Field label="ملف درجات الحرارة NPY" name="file" type="file" />
              <Select label="الوحدة" name="units" defaultValue="C">
                <option value="C">Celsius °C</option>
                <option value="K">Kelvin K</option>
              </Select>
              <Field
                label="منطقة الأنبوب"
                name="roi"
                defaultValue="[0,0,1,1]"
              />
              <label className="checkbox">
                <input type="checkbox" name="calibrated" value="true" />
                أصرّح أن بيانات المعايرة والانبعاثية راجعتها
              </label>
              <button className="primary" disabled={busy}>
                استيراد وحساب Tmax
              </button>
            </form>
          )}
          {modal.type === "document" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  () => api("/documents", new FormData(e.currentTarget)),
                  "استُخرج النص؛ راجع الصفحات لاعتماد الوقائع",
                );
              }}
            >
              <Select
                label="السرج المرتبط"
                name="saddle_id"
                defaultValue={saddle?.id}
              >
                {saddles.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
              <Field label="تقرير PDF، حتى 10 MB" name="file" type="file" />
              <p className="muted">
                التقرير المصور قد يحتاج OCR. الاستخراج لا يعتمد وقائع تلقائيًا.
              </p>
              <button className="primary" disabled={busy}>
                استخراج النص
              </button>
            </form>
          )}
          {modal.type === "sourceEvent" && (
            <>
              <div className="pdf-text">
                {modal.item.pages.map((p: any) => (
                  <section key={p.page}>
                    <h4>صفحة {p.page}</h4>
                    <pre>{p.text || "لا يوجد نص قابل للاستخراج"}</pre>
                  </section>
                ))}
              </div>
              <form
                onSubmit={(e) => {
                  const values = form(e);
                  run(
                    () =>
                      api("/documents/" + modal.item.id + "/events", {
                        ...values,
                        page: Number(values.page),
                      }),
                    "تم اعتماد الواقعة مع مصدرها",
                  );
                }}
              >
                <Field
                  label="رقم الصفحة"
                  name="page"
                  type="number"
                  defaultValue="1"
                />
                <Field label="اقتباس حرفي من النص أعلاه" name="quote" area />
                <Field label="وصف الواقعة" name="summary" />
                <Select
                  label="نوع الواقعة"
                  name="event_type"
                  defaultValue="inspection"
                >
                  <option value="repair">إصلاح سابق</option>
                  <option value="inspection">فحص سابق</option>
                  <option value="other">واقعة أخرى</option>
                </Select>
                <Field
                  label="تاريخ الواقعة إن ذكره المصدر"
                  name="event_date"
                  required={false}
                />
                <button className="primary" disabled={busy}>
                  اعتماد وربط بسجل السرج
                </button>
              </form>
            </>
          )}
          {modal.type === "placements" && (
            <div>
              {modal.items
                .sort((a: any, b: any) => b.score - a.score)
                .map((r: any) => (
                  <div className="placement-row" key={r.saddle_id}>
                    <h3>
                      {nameOf(r.saddle_id)} · {r.score} نقاط
                    </h3>
                    <p>{r.reasons.join(" · ") || "لا عوامل مسجلة"}</p>
                    <small>{r.note}</small>
                    <form
                      onSubmit={(e) => {
                        const values = form(e);
                        run(
                          () =>
                            api("/placements", {
                              ...values,
                              saddle_id: r.saddle_id,
                            }),
                          "حُفظ قرار الأولوية",
                          false,
                        );
                      }}
                    >
                      <Select
                        label="القرار"
                        name="decision"
                        defaultValue="approved"
                      >
                        <option value="approved">اعتماد الأولوية</option>
                        <option value="rejected">رفض الاقتراح</option>
                      </Select>
                      <Field label="مبرر القرار الهندسي" name="notes" />
                      <button disabled={busy || !can("operator", "inspector")}>
                        حفظ القرار
                      </button>
                    </form>
                  </div>
                ))}
            </div>
          )}
          {modal.type === "history" && (
            <div className="history-list">
              {modal.items.map((i: any) => (
                <div key={i.id}>
                  <Clock size={17} />
                  <div>
                    <strong>{i.action}</strong>
                    <small>
                      {fmt(i.at)} · {i.actor}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          )}
          {modal.type === "episode" && (
            <>
              <Badge value={modal.item.source} />
              <p>{modal.item.assessment.method}</p>
              <p>
                حزم صالحة: {modal.item.assessment.valid_count} /{" "}
                {modal.item.assessment.total_count}
              </p>
              {modal.item.assessment.alerts.map((a: any, i: number) => (
                <div className="finding" key={i}>
                  <strong>{a.title}</strong>
                  <p>
                    ساعة المحاكاة: {n(a.simulation_time_s / 3600)} · {a.note}
                  </p>
                </div>
              ))}
              {!modal.item.assessment.alerts.length && (
                <p>لم يُسجل تنبيه مؤكد لهذا التشغيل.</p>
              )}
            </>
          )}
          {modal.type === "user" && (
            <form
              onSubmit={(e) => {
                const values = form(e);
                run(() => api("/users", values), "تمت إضافة المستخدم");
              }}
            >
              <Field
                label="اسم الدخول (حروف إنجليزية، أرقام أو _)"
                name="name"
              />
              <Select label="الدور" name="role" defaultValue="operator">
                <option value="operator">مشغل الأصول</option>
                <option value="drone">مشغل الدرون</option>
                <option value="inspector">مفتش</option>
              </Select>
              <Field
                label="كلمة المرور، 12 محرفًا على الأقل"
                name="password"
                type="password"
              />
              <button className="primary" disabled={busy}>
                إضافة
              </button>
            </form>
          )}
        </Modal>
      )}
      {busy && (
        <div className="busy-indicator" role="status">
          جاري تنفيذ الطلب…
        </div>
      )}
      {toast && toast.text && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? (
            <TriangleAlert size={20} />
          ) : (
            <CircleCheck size={20} />
          )}
          <span>{toast.text}</span>
          <button
            className="icon-button"
            onClick={() => setToast(null)}
            aria-label="إغلاق الرسالة"
          >
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}

function customerSerialFromPath() {
  const value = location.pathname.replace(/^\/cylinder\/?/, '').replace(/\/$/, '');
  try { return value ? decodeURIComponent(value) : null; } catch { return value; }
}

function Root() {
  const publicPage = location.pathname === '/cylinder' || location.pathname.startsWith('/cylinder/');
  const [serial, setSerial] = useState(customerSerialFromPath);
  useEffect(() => {
    const update = () => setSerial(customerSerialFromPath());
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  if (!publicPage) return <App />;
  return <div className="customer-public-shell" dir="rtl"><header className="customer-public-header"><Brand/><span>هوية الأسطوانة · سجل الرحلات</span></header><main>
    <LpgCustomerReport standalone requestedSerial={serial} onSelect={value => { history.pushState(null, '', `/cylinder/${encodeURIComponent(value)}`); setSerial(value); }} />
  </main></div>;
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
