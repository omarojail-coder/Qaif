import { useEffect, useState } from "react";
import {
  ArrowRight,
  Plus,
  Minus,
  LocateFixed,
  Radio,
  Route,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { plannedCount, planningWindow } from "./mapMath";
import { DISPLAY_LOCALE } from "./locale";

const n = (v: number) => v.toLocaleString(DISPLAY_LOCALE);
const positions: Record<string, [number, number]> = {
  "P-1": [490, 550],
  "P-2": [380, 235],
  "P-3": [775, 167],
  "P-4": [785, 545],
  "P-5": [525, 310],
  "P-6": [790, 440],
  "P-7": [415, 455],
  "P-8": [365, 72],
};
const names: Record<string, string> = {
  "P-1": "الجبيل · غاز",
  "P-2": "شرق–غرب",
  "P-3": "بقيق–رأس تنورة",
  "P-4": "الشيبة–بقيق",
  "P-5": "القطيف–بقيق",
  "P-6": "AB-4",
  "P-7": "حرض–الحوية",
  "P-8": "التابلاين · تاريخي",
};
const activate = (e: any, fn: () => void) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fn();
  }
};

export default function MetroMap({
  assets = [],
  saddles,
  pipelines,
  selected,
  onSelect,
  alerts,
  selectedPipeline = "",
  onPipelineSelect,
  onlyAlerts = false,
}: any) {
  const [features, setFeatures] = useState<any[]>([]);
  const [zoom, setZoom] = useState(1);
  const [page, setPage] = useState(0);
  const [lengths, setLengths] = useState<Record<string, string>>({});
  const [point, setPoint] = useState<number | null>(null);
  useEffect(() => {
    fetch("/countries.geojson")
      .then((r) => r.json())
      .then((g) => setFeatures(g.features))
      .catch(() => {});
  }, []);
  useEffect(() => {
    setZoom(1);
    setPage(0);
    setPoint(null);
  }, [selectedPipeline]);
  const route = pipelines.find((p: any) => p.id === selectedPipeline);
  const linked = (id: string) =>
    saddles.filter((s: any) => s.pipeline_id === id);
  const registered = linked(route?.id);
  const active = (id: string) =>
    alerts.some((a: any) => a.saddle_id === id && a.status === "new");
  const shown = registered.filter((s: any) => !onlyAlerts || active(s.id));
  const length =
    route && lengths[route.id] !== undefined
      ? Number(lengths[route.id])
      : route?.length_km;
  const count = plannedCount(length, route?.lifecycle === "decommissioned");
  const window = count ? planningWindow(count, page) : null;
  const xy = ([lon, lat]: number[]) => [(lon - 33) * 37, (33.5 - lat) * 32];
  const path = (ring: number[][]) =>
    ring.map((p, i) => `${i ? "L" : "M"}${xy(p).join(",")}`).join(" ") + "Z";
  return (
    <section className="metro-workspace" aria-label="خريطة خطوط الأنابيب">
      <div className="metro-heading">
        <div>
          <Route size={19} />
          <strong>{route ? route.name : "شبكة الخطوط · عرض المملكة"}</strong>
        </div>
        {route ? (
          <button onClick={() => onPipelineSelect("")}>
            <ArrowRight size={16} />
            كل المسارات
          </button>
        ) : (
          <span className="muted small">اختر خطًا لعرض التفاصيل</span>
        )}
      </div>
      <div className={`map-view metro-map ${route ? "detail" : "overview"}`}>
        <svg
          viewBox={`${(960 - 960 / zoom) / 2} ${(620 - 620 / zoom) / 2} ${960 / zoom} ${620 / zoom}`}
          role="group"
          aria-label={
            route
              ? `تفاصيل مسار ${route.name}`
              : "خريطة مترو تخطيطية لخطوط المملكة؛ ليست مقياس مسافات"
          }
        >
          <rect width="960" height="620" fill={route ? "#FBFAFF" : "#F8F8FD"} />
          {!route ? (
            <>
              <g opacity=".52">
                {features.flatMap((f, i) =>
                  (f.geometry.type === "Polygon"
                    ? [f.geometry.coordinates]
                    : f.geometry.coordinates
                  ).map((polygon: number[][][], j: number) => (
                    <path
                      key={`${i}-${j}`}
                      d={polygon.map(path).join(" ")}
                      fill={
                        f.properties.ADMIN === "Saudi Arabia"
                          ? "#EDEAF8"
                          : "#F5F5FA"
                      }
                      stroke="#DDD9EB"
                      strokeWidth="1"
                    />
                  )),
                )}
              </g>
              <text x="360" y="535" className="metro-country">
                المملكة العربية السعودية
              </text>
              <text x="890" y="280" className="metro-water">
                الخليج العربي
              </text>
              <text x="170" y="460" className="metro-water">
                البحر الأحمر
              </text>
              {assets.map((asset: any) => {
                const [x, y] = xy([asset.lon, asset.lat]);
                return (
                  <g
                    key={asset.id}
                    className="asset-dot"
                    transform={`translate(${x} ${y})`}
                    role="button"
                    tabIndex={0}
                    aria-label={`أصل ${asset.name}؛ موقع تقريبي`}
                    onClick={() => onSelect(asset.id)}
                    onKeyDown={(e) => activate(e, () => onSelect(asset.id))}
                  >
                    <circle
                      r={selected === asset.id ? 13 : 6}
                      fill={selected === asset.id ? "#F2EAFF" : "white"}
                      stroke={asset.type === "gas" ? "#9874D4" : "#535DC2"}
                      strokeWidth="2"
                    />
                    {asset.type === "gas" ? (
                      <path d="M0-3 3 0 0 3-3 0Z" fill="#9874D4" />
                    ) : (
                      <rect
                        x="-2.5"
                        y="-2.5"
                        width="5"
                        height="5"
                        fill="#535DC2"
                      />
                    )}
                    {selected === asset.id && (
                      <text y="-19" className="metro-station-label">
                        {asset.name}
                      </text>
                    )}
                    <title>{asset.name} · موقع تقريبي في دليل الأصول</title>
                  </g>
                );
              })}
              {pipelines.map((p: any) => (
                <g
                  key={p.id}
                  className="metro-route"
                  role="button"
                  tabIndex={0}
                  aria-label={`تفاصيل ${p.name}`}
                  onClick={() => onPipelineSelect(p.id)}
                  onKeyDown={(e) => activate(e, () => onPipelineSelect(p.id))}
                >
                  <polyline
                    points={p.metro_points
                      .map((v: number[]) => v.join(","))
                      .join(" ")}
                    fill="none"
                    stroke="transparent"
                    strokeWidth="24"
                  />
                  <polyline
                    points={p.metro_points
                      .map((v: number[]) => v.join(","))
                      .join(" ")}
                    fill="none"
                    stroke={p.color}
                    strokeWidth={p.medium === "oil" ? 7 : 5}
                    strokeDasharray={
                      p.lifecycle === "decommissioned"
                        ? "9 7"
                        : p.medium === "gas"
                          ? "3 8"
                          : undefined
                    }
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </g>
              ))}
              {Array.from(
                new Map(
                  pipelines
                    .flatMap((p: any) => p.stations)
                    .map((s: any) => [s.id, s]),
                ).values(),
              ).map((s: any) => (
                <g key={s.id}>
                  <circle
                    cx={s.x}
                    cy={s.y}
                    r="7"
                    fill="white"
                    stroke="#55516F"
                    strokeWidth="2"
                  />
                  <text
                    x={s.x}
                    y={s.y + (s.id === "abqaiq" ? -20 : 27)}
                    className="metro-station-label"
                  >
                    {s.name}
                  </text>
                </g>
              ))}
              {pipelines.map((p: any) => {
                const [x, y] = positions[p.id] || [400, 300];
                return (
                  <g
                    key={p.id}
                    className="metro-route-label"
                    role="button"
                    tabIndex={0}
                    aria-label={`تفاصيل ${p.name}، ${linked(p.id).length} أسرجة مسجلة`}
                    onClick={() => onPipelineSelect(p.id)}
                    onKeyDown={(e) => activate(e, () => onPipelineSelect(p.id))}
                  >
                    <rect
                      x={x - 88}
                      y={y - 22}
                      width="176"
                      height="44"
                      rx="7"
                      fill="white"
                      stroke={p.color}
                      strokeWidth="1.5"
                    />
                    <text x={x} y={y - 4} className="metro-route-name">
                      {names[p.id] || p.name}
                    </text>
                    <text x={x} y={y + 13} className="metro-count">
                      {n(linked(p.id).length)} مسجّلة
                      {plannedCount(
                        p.length_km,
                        p.lifecycle === "decommissioned",
                      ) !== null &&
                        ` · ${n(plannedCount(p.length_km)!)} مقترحة`}
                    </text>
                  </g>
                );
              })}
              <g
                transform="translate(260 390)"
                className="facility-illustration"
                aria-hidden="true"
              >
                <path
                  d="M0 42V17h13v25h10V8h13v34h9V23h13v19H0Z"
                  fill="#A98CF6"
                  opacity=".65"
                />
                <path
                  d="M7 6V0m23 2V-5m22 20v-7"
                  stroke="#6772E8"
                  strokeWidth="3"
                />
                <text x="27" y="62">
                  مرافق ومصافي
                </text>
              </g>
              <g
                transform="translate(855 100)"
                className="facility-illustration"
                aria-hidden="true"
              >
                <path
                  d="M0 40V18h10v22h8V4h10v36h10V15h10v25Z"
                  fill="#F280A4"
                  opacity=".65"
                />
                <path d="M8 0h25m-12-5v10" stroke="#D57B7D" strokeWidth="3" />
                <text x="24" y="59">
                  منشآت الطاقة
                </text>
              </g>
            </>
          ) : (
            <>
              <text x="480" y="73" className="metro-detail-title">
                {route.name}
              </text>
              <text x="480" y="106" className="metro-detail-subtitle">
                {route.lifecycle === "decommissioned"
                  ? "مسار تاريخي متوقف"
                  : "المحطات الرئيسية · ترتيب تخطيطي"}
              </text>
              <path
                d="M100 190H850"
                stroke={route.color}
                strokeWidth="9"
                strokeDasharray={
                  route.lifecycle === "decommissioned" ? "12 10" : undefined
                }
                strokeLinecap="round"
              />
              {route.stations.map((s: any, i: number) => (
                <g
                  key={s.id}
                  transform={`translate(${100 + (i * 750) / Math.max(1, route.stations.length - 1)} 190)`}
                >
                  <circle
                    r="12"
                    fill="white"
                    stroke={route.color}
                    strokeWidth="4"
                  />
                  <text y="40" className="metro-station-label">
                    {s.name}
                  </text>
                </g>
              ))}
              <text x="480" y="295" className="metro-detail-subtitle">
                الأسرجة المسجلة على هذا الخط: {n(registered.length)}
              </text>
              {shown.length ? (
                shown.map((s: any, i: number) => (
                  <g
                    key={s.id}
                    transform={`translate(${480 + (i - (shown.length - 1) / 2) * 175} 348)`}
                    role="button"
                    tabIndex={0}
                    aria-label={`فتح سجل ${s.name}`}
                    className="saddle-dot"
                    onClick={() => onSelect(s.id)}
                    onKeyDown={(e) => activate(e, () => onSelect(s.id))}
                  >
                    <circle
                      r="22"
                      fill={active(s.id) ? "#FCE8EF" : "white"}
                      stroke={active(s.id) ? "#A54459" : route.color}
                      strokeWidth={selected === s.id ? 4 : 2}
                    />
                    <text dy="5" className="metro-saddle-number">
                      {s.id.replace("S-", "")}
                    </text>
                    <text y="43" className="metro-count">
                      {s.name.split("·")[0]}
                    </text>
                    {active(s.id) && <path d="M18-25h8v8h-8Z" fill="#A54459" />}
                  </g>
                ))
              ) : (
                <text x="480" y="350" className="metro-detail-subtitle">
                  {onlyAlerts
                    ? "لا توجد أسرجة ذات تنبيه جديد على هذا الخط"
                    : "لا توجد أسرجة مسجلة لهذا الخط حتى الآن"}
                </text>
              )}
              {window && (
                <>
                  <text x="480" y="435" className="metro-detail-subtitle">
                    نقاط التخطيط المقترحة · كل 31 مترًا
                  </text>
                  <path
                    d="M85 485H875"
                    stroke={route.color}
                    strokeWidth="3"
                    strokeDasharray="5 5"
                  />
                  {window.points.map((p, i) => (
                    <g
                      key={p.index}
                      role="button"
                      tabIndex={0}
                      aria-label={`نقطة تخطيط ${p.index} عند ${p.meters} متر؛ غير مثبتة`}
                      className="planned-dot"
                      onClick={() => setPoint(p.meters)}
                      onKeyDown={(e) => activate(e, () => setPoint(p.meters))}
                      transform={`translate(${85 + (i * 790) / Math.max(1, window.points.length - 1)} 485)`}
                    >
                      <circle
                        r="7"
                        fill={point === p.meters ? route.color : "white"}
                        stroke={route.color}
                        strokeWidth="2"
                      />
                      {(i === 0 ||
                        i === window.points.length - 1 ||
                        window.points.length <= 8) && (
                        <text y="28" className="metro-count">
                          {n(p.meters)} م
                        </text>
                      )}
                    </g>
                  ))}
                  <text x="480" y="555" className="metro-detail-subtitle">
                    {point !== null
                      ? `موضع مقترح عند ${n(point)} متر · لا يوجد جهاز أو سجل قياس`
                      : "النقاط المجوفة مقترحة؛ اضغط نقطة لعرض موضعها"}
                  </text>
                </>
              )}
            </>
          )}
        </svg>
        <div className="map-controls">
          <button
            aria-label="تكبير الخريطة"
            onClick={() => setZoom(Math.min(zoom + 0.2, 1.8))}
          >
            <Plus size={17} />
          </button>
          <button
            aria-label="تصغير الخريطة"
            onClick={() => setZoom(Math.max(zoom - 0.2, 1))}
          >
            <Minus size={17} />
          </button>
          <button aria-label="إعادة ضبط الخريطة" onClick={() => setZoom(1)}>
            <LocateFixed size={17} />
          </button>
        </div>
      </div>
      <div className="metro-legend">
        <span>
          <i className="legend-line oil" />
          نفط
        </span>
        <span>
          <i className="legend-line gas" />
          غاز
        </span>
        <span>
          <i className="legend-line history" />
          تاريخي متوقف
        </span>
        <span>
          <Radio size={15} />
          سرج مسجّل
        </span>
        <span>
          <i className="legend-planned" />
          نقطة مقترحة
        </span>
        <span className="muted">الألوان تميز المسارات</span>
        <span className="muted">◇ مرفق غاز · ▪ مصفاة · مواقع تقريبية</span>
      </div>
      {route ? (
        <div className="route-information">
          <div className="route-facts">
            <span>
              الأسرجة المسجلة<strong>{n(registered.length)}</strong>
            </span>
            <span>
              نقاط مقترحة على طول التخطيط
              <strong>{count !== null ? n(count) : "—"}</strong>
            </span>
            <span>
              تباعد التخطيط<strong>31 م</strong>
            </span>
          </div>
          {route.lifecycle !== "decommissioned" && (
            <label className="planning-length">
              طول التخطيط بالكيلومتر
              <input
                type="number"
                min="0.001"
                max="10000"
                step="0.001"
                aria-label="طول التخطيط بالكيلومتر"
                placeholder="أدخل طول الخط"
                value={lengths[route.id] ?? route.length_km ?? ""}
                onChange={(e) => {
                  setLengths({ ...lengths, [route.id]: e.target.value });
                  setPage(0);
                  setPoint(null);
                }}
              />
              <small>
                {lengths[route.id] !== undefined
                  ? "افتراض أدخلته للتخطيط"
                  : route.length_km
                    ? "طول منشور؛ العدد المقترح حساب تخطيطي"
                    : "لم يتوفر طول موثق؛ لا يُحسب عدد افتراضي"}
              </small>
            </label>
          )}
          {window && (
            <div className="planning-pagination">
              <button
                aria-label="نقاط التخطيط السابقة"
                disabled={window.page === 0}
                onClick={() => {
                  setPage(window.page - 1);
                  setPoint(null);
                }}
              >
                <ChevronRight size={17} />
              </button>
              <span>
                النقاط {n(window.points[0].index)}–
                {n(window.points[window.points.length - 1].index)} من{" "}
                {n(count!)}
                <small>نافذة تفصيلية؛ المسافات محسوبة على طول التخطيط</small>
              </span>
              <button
                aria-label="نقاط التخطيط التالية"
                disabled={window.page + 1 === window.pages}
                onClick={() => {
                  setPage(window.page + 1);
                  setPoint(null);
                }}
              >
                <ChevronLeft size={17} />
              </button>
              <label>
                نافذة رقم
                <input
                  aria-label="نافذة نقاط التخطيط"
                  type="number"
                  min="1"
                  max={window.pages}
                  value={window.page + 1}
                  onChange={(e) => {
                    setPage(
                      Math.max(
                        0,
                        Math.min(window.pages - 1, Number(e.target.value) - 1),
                      ),
                    );
                    setPoint(null);
                  }}
                />
              </label>
            </div>
          )}
          <p>{route.note}</p>
          {route.source_url && (
            <a href={route.source_url} target="_blank" rel="noreferrer">
              {route.source_title}
              <ExternalLink size={13} />
            </a>
          )}
          {route.length_source_url && (
            <a href={route.length_source_url} target="_blank" rel="noreferrer">
              مصدر الطول المنشور
              <ExternalLink size={13} />
            </a>
          )}
        </div>
      ) : (
        <div className="metro-route-index">
          {pipelines.map((p: any) => (
            <button key={p.id} onClick={() => onPipelineSelect(p.id)}>
              <i style={{ background: p.color }} />
              <strong>{names[p.id] || p.name}</strong>
              <span>
                {n(linked(p.id).length)} مسجّلة
                {plannedCount(p.length_km, p.lifecycle === "decommissioned") !==
                  null && ` · ${n(plannedCount(p.length_km)!)} مقترحة`}
              </span>
              <ChevronLeft size={14} />
            </button>
          ))}
        </div>
      )}
      <p className="metro-disclaimer">
        الخطوط الرئيسية الموثقة علنًا مع مسار العرض؛ اكتمال الشبكة يتطلب سجل
        المالك. الرسم والمحطات تقريبية، و31 م افتراض للتخطيط.
      </p>
    </section>
  );
}
