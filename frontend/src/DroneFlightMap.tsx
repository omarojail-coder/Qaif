import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as GLMap, type GeoJSONSource } from "maplibre-gl";
import { LocateFixed, Plane, Play, RotateCcw } from "lucide-react";
import { api, type RecordData } from "./api";
import { facilityIconSvg } from "./FacilityIcon";
import { saddleIconSvg, saddleStatus } from "./saddleMarkers";
import { DISPLAY_LOCALE } from "./locale";
import { DRONE_ICON, flightPoint, flightState, travelledPath, type FlightPlan } from "./droneFlight";
import "./drone-flight.css";

type Packet = { plan: FlightPlan | null; server_now_ms: number };
const line = (positions: number[][]) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: positions } }) as const;

export default function DroneFlightMap({ mission, saddle, alerts, canStart, onSaved, onClockSync }: {
  mission: RecordData; saddle?: RecordData; alerts: RecordData[]; canStart: boolean; onSaved: () => Promise<any>; onClockSync: (offset: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null), map = useRef<GLMap | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]), drone = useRef<maplibregl.Marker | null>(null);
  const activeId = useRef(mission.id); activeId.current = mission.id;
  const [plan, setPlan] = useState<FlightPlan | null>(null), [offset, setOffset] = useState(0);
  const [ready, setReady] = useState(false), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [tileError, setTileError] = useState(false), [revision, setRevision] = useState(0);
  const [info, setInfo] = useState({ progress: 0, phase: "planned", remaining: 120 });
  const [reduced, setReduced] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const initial = useRef<FlightPlan | null>(null); initial.current = plan;
  const status = saddle ? saddleStatus(saddle, alerts) : "unknown";

  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReduced(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);

  useEffect(() => {
    let alive = true;
    // The component is keyed by mission ID. Keep the same map alive on a replay or snapshot refresh.
    setLoading(true); setError("");
    api<Packet>(`/missions/${mission.id}/flight`).then(packet => {
      if (!alive) return;
      const clockOffset = packet.server_now_ms - Date.now();
      setOffset(clockOffset); onClockSync(clockOffset); setPlan(packet.plan); setLoading(false);
    }).catch(e => { if (alive) { setError(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [mission.id, mission.virtual_flight?.started_ms, mission.virtual_flight?.stopped_ms, revision, onClockSync]);

  const fit = (value: FlightPlan) => {
    const instance = map.current;
    if (!instance) return;
    const bounds = new maplibregl.LngLatBounds(value.origin.position, value.origin.position);
    value.path.forEach(p => bounds.extend(p));
    instance.fitBounds(bounds, { padding: { top: 58, bottom: 65, left: 52, right: 52 }, maxZoom: 13, duration: 0 });
  };

  useEffect(() => {
    if (!host.current || !plan) return;
    let alive = true, instance: GLMap | undefined, resize: ResizeObserver | undefined;
    setReady(false); setTileError(false);
    try {
      instance = new maplibregl.Map({
        container: host.current, center: plan.origin.position, zoom: 9, minZoom: 3, maxZoom: 17,
        renderWorldCopies: false, attributionControl: false, scrollZoom: false, dragRotate: false, pitchWithRotate: false,
        canvasContextAttributes: { preserveDrawingBuffer: true },
        locale: { "NavigationControl.ZoomIn": "تكبير مسار الدرون", "NavigationControl.ZoomOut": "تصغير مسار الدرون", "AttributionControl.ToggleAttribution": "مصادر خريطة الدرون" },
        style: {
          version: 8,
          sources: {
            satellite: { type: "raster", tiles: ["https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 19, attribution: "Source: Esri, Vantor, Earthstar Geographics, GIS User Community" },
            route: { type: "geojson", data: line(plan.path) },
            covered: { type: "geojson", data: line([plan.path[0], plan.path[0]]) },
          },
          layers: [
            { id: "background", type: "background", paint: { "background-color": "#283337" } },
            { id: "imagery", type: "raster", source: "satellite", paint: { "raster-saturation": -0.2, "raster-brightness-max": 0.85 } },
            { id: "route-halo", type: "line", source: "route", paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.75 } },
            { id: "route-plan", type: "line", source: "route", paint: { "line-color": "#b7bdfb", "line-width": 3, "line-dasharray": [3, 2] } },
            { id: "route-covered", type: "line", source: "covered", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#6772E8", "line-width": 4 } },
          ],
        },
      });
      map.current = instance;
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
      instance.addControl(new maplibregl.ScaleControl({ maxWidth: 80, unit: "metric" }), "bottom-left");
      instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
      instance.touchZoomRotate.disableRotation();
      fit(plan);
      instance.getCanvas().setAttribute("role", "img");
      instance.getCanvas().setAttribute("aria-label", `مسار الدرون من ${plan.origin.name} إلى ${plan.target.name}`);
      instance.on("load", () => { if (alive) setReady(true); });
      instance.on("error", event => { if (alive && ((event as any).sourceId === "satellite" || event.error?.message.includes("arcgisonline"))) setTileError(true); });
      instance.on("sourcedata", event => { if (alive && event.sourceId === "satellite" && event.isSourceLoaded) setTileError(false); });
      resize = new ResizeObserver(() => instance?.resize()); resize.observe(host.current);
    } catch { setError("تعذر عرض خريطة مسار الدرون."); }
    return () => {
      alive = false; setReady(false); resize?.disconnect(); markers.current.forEach(m => m.remove()); markers.current = [];
      drone.current?.remove(); drone.current = null; instance?.remove(); map.current = null;
    };
  }, [!!plan]);

  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance || !plan) return;
    const routeSource = instance.getSource("route") as GeoJSONSource | undefined;
    if (!routeSource) return;
    markers.current.forEach(m => m.remove()); markers.current = [];
    routeSource.setData(line(plan.path));
    fit(plan);
    const origin = document.createElement("span"); origin.className = "flight-origin";
    origin.innerHTML = facilityIconSvg(plan.origin.type); origin.title = plan.origin.name;
    origin.setAttribute("role", "img"); origin.setAttribute("aria-label", `الانطلاق · ${plan.origin.name}`);
    markers.current.push(new maplibregl.Marker({ element: origin, anchor: "bottom", offset: [0, -20] }).setLngLat(plan.origin.position).addTo(instance));
    const target = document.createElement("span"); target.className = `flight-target ${status}`;
    target.innerHTML = saddleIconSvg(); const id = document.createElement("b"); id.dir = "ltr"; id.textContent = plan.target.id; target.append(id);
    target.setAttribute("role", "img"); target.setAttribute("aria-label", `الهدف · ${plan.target.name}`);
    markers.current.push(new maplibregl.Marker({ element: target, anchor: "top", offset: [0, 20] }).setLngLat(plan.target.position).addTo(instance));
  }, [ready, plan, status]);

  useEffect(() => {
    const instance = map.current;
    if (!plan) return;
    setInfo(flightState(plan, Date.now() + offset, mission.status === "cancelled"));
    if (!ready || !instance || !instance.getSource("covered")) return;
    drone.current?.remove(); drone.current = null;
    const icon = document.createElement("span"); icon.className = "flight-drone"; icon.innerHTML = DRONE_ICON;
    icon.dataset.missionId = mission.id; icon.setAttribute("role", "img"); icon.setAttribute("aria-label", "الدرون في مسار الجولة الافتراضي");
    if (plan.started_ms !== null) drone.current = new maplibregl.Marker({ element: icon, anchor: "center" }).setLngLat(plan.origin.position).addTo(instance);
    let raf = 0, lastPaint = -Infinity, lastText = -Infinity;
    const draw = (time: number) => {
      const coveredSource = instance.getSource("covered") as GeoJSONSource | undefined;
      if (map.current !== instance || !coveredSource) return;
      const state = flightState(plan, Date.now() + offset, mission.status === "cancelled");
      if (time-lastPaint >= (reduced ? 1000 : 32) || state.phase !== "flying") {
        const point = flightPoint(plan.path, state.progress);
        drone.current?.setLngLat(point);
        icon.dataset.position = point.join(","); icon.dataset.progress = String(state.progress);
        coveredSource.setData(line(travelledPath(plan.path, state.progress)));
        lastPaint = time;
      }
      if (time-lastText >= 250 || state.phase !== "flying") { setInfo(state); lastText = time; }
      if (state.phase === "flying") raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); drone.current?.remove(); drone.current = null; };
  }, [ready, plan, offset, mission.id, mission.status, reduced]);

  const start = async () => {
    const id = mission.id;
    setBusy(true); setError("");
    try {
      const packet = await api<Packet>(`/missions/${id}/flight/start`, { restart: info.phase === "arrived" });
      if (activeId.current !== id) return;
      const clockOffset = packet.server_now_ms - Date.now();
      setPlan(packet.plan); setOffset(clockOffset); onClockSync(clockOffset); await onSaved();
    } catch (e: any) { if (activeId.current === id) setError(e.message); }
    finally { setBusy(false); }
  };
  const remaining = `${Math.floor(info.remaining/60)}:${String(info.remaining%60).padStart(2,"0")}`;
  const phases: Record<string,string> = { planned: "جاهزة للاستعراض", flying: "الدرون تتجه إلى السرج", arrived: "وصلت الدرون إلى الهدف", stopped: "توقفت الرحلة" };
  return (
    <section className="panel drone-flight-panel" data-mission-id={mission.id} data-phase={info.phase} data-progress={info.progress}>
      <div className="panel-heading"><h3><Plane size={18} />مسار الدرون</h3><span className="flight-virtual-tag">مسار افتراضي</span></div>
      <div className="drone-flight-frame">
        <div ref={host} className="drone-flight-map" role="region" aria-label={`خريطة مسار الجولة ${mission.id}`} />
        {plan && <button className="flight-fit" title="عرض المسار كاملًا" aria-label="عرض المسار كاملًا" onClick={() => fit(plan)}><LocateFixed size={17}/></button>}
        {loading && <p className="flight-message" role="status">جاري تجهيز المسار…</p>}
        {!loading && !plan && !error && <p className="flight-message">لا يتوفر موقع سرج ومرفق انطلاق صالحان لهذه الجولة.</p>}
        {tileError && <p className="flight-tile-error" role="status">تعذر تحميل صور الأقمار؛ المسار متاح.</p>}
      </div>
      {plan && <>
        <div className="flight-endpoints"><div><span>الانطلاق · أقرب مرفق</span><strong>{plan.origin.name}</strong></div><div><span>الهدف</span><strong>{plan.target.name}</strong></div></div>
        <div className="flight-progress"><span aria-live="polite">{phases[info.phase]}</span><strong dir="ltr">{Math.floor(info.progress*100)}%</strong></div>
        <progress max="1" value={info.progress} aria-label="تقدم رحلة الدرون" />
        <div className="flight-meta"><span>المسافة الجغرافية <b dir="ltr">{plan.distance_km.toLocaleString(DISPLAY_LOCALE,{maximumFractionDigits:1})} km</b></span><span>زمن العرض المتبقي <b dir="ltr">{remaining}</b></span></div>
        {canStart && ["planned","arrived"].includes(info.phase) && mission.status !== "cancelled" && <button className="flight-start" disabled={busy} onClick={start}>{info.phase === "arrived" ? <RotateCcw size={15}/> : <Play size={15}/>} {info.phase === "arrived" ? "إعادة استعراض الرحلة" : "استعراض الرحلة"}</button>}
      </>}
      {error && <p className="flight-error" role="alert">{error} <button onClick={() => setRevision(v=>v+1)}>إعادة المحاولة</button></p>}
    </section>
  );
}
