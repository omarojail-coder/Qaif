import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type Map as GLMap, type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  LocateFixed,
  Radio,
  Satellite,
  Waves,
  Layers2,
} from "lucide-react";
import FacilityIcon, { facilityIconSvg, facilityGroupSvg } from "./FacilityIcon";
import { boxesOverlap, groupFacilities, placeMarker, type ScreenBox, type ScreenPoint } from "./markerLayout";
import { plannedCount, planningWindow } from "./mapMath";
import {
  inBoundary,
  polygons,
  routeFeatures,
  pointAlong,
  type Position,
} from "./geoRoutes";
import { displayPosition } from "./mapLocations";
import { DISPLAY_LOCALE } from "./locale";
import { createPipeTexture } from "./pipeTexture";
import { hasSaddleAlert, saddleStatus, saddleVisible, saddleIconSvg, SADDLE_ICON_BODY, SADDLE_STATUS_LABELS } from "./saddleMarkers";
import "./satellite.css";

const n = (v: number) => v.toLocaleString(DISPLAY_LOCALE);
const COUNTRY_BOUNDS: [[number, number], [number, number]] = [
  [34.4, 16.25],
  [55.7, 32.25],
];
const empty = { type: "FeatureCollection", features: [] } as const;
const imagery =
  "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const reduced = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const duration = () => (reduced() ? 0 : 550);

const pipeWidth = (selectedId = "", casing = 0): any => {
  const size = (width: number) =>
    selectedId
      ? ["case", ["==", ["get", "route_id"], selectedId], width + 1.4 + casing, width * 0.65 + casing]
      : width + casing;
  return ["interpolate", ["linear"], ["zoom"], 4, size(3.6), 7, size(6), 10, size(9), 14, size(13)];
};

export default function SatelliteMap(props: any) {
  const {
    assets = [],
    saddles = [],
    pipelines = [],
    selected,
    onSelect,
    alerts = [],
    selectedPipeline = "",
    onPipelineSelect,
    onlyAlerts = false,
  } = props;
  const host = useRef<HTMLDivElement>(null),
    map = useRef<GLMap | null>(null),
    current = useRef(props);
  current.current = props;
  const [loaded, setLoaded] = useState(false),
    [geo, setGeo] = useState<any>(null),
    [error, setError] = useState(""),
    [tileError, setTileError] = useState(false),
    [retry, setRetry] = useState(0);
  const [showNames, setShowNames] = useState(true),
    [history, setHistory] = useState(false),
    [zoom, setZoom] = useState(5),
    [page, setPage] = useState(0),
    [lengths, setLengths] = useState<Record<string, string>>({}),
    [point, setPoint] = useState<number | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]),
    priorSelection = useRef(selected),
    priorRoute = useRef<string | null>(null);
  const [planningView, setPlanningView] = useState(false);
  const [viewRevision, setViewRevision] = useState(0);
  const clusterPopup = useRef<maplibregl.Popup | null>(null);
  const route = pipelines.find((p: any) => p.id === selectedPipeline);
  const selectedSaddle = saddles.find((s: any) => s.id === selected);
  const registered = saddles.filter(
    (s: any) => s.pipeline_id === selectedPipeline,
  );
  const active = (id: string) => hasSaddleAlert(id, alerts);
  const planningLength =
    route && lengths[route.id] !== undefined
      ? Number(lengths[route.id])
      : route?.length_km;
  const count = plannedCount(
    planningLength,
    route?.lifecycle === "decommissioned",
  );
  const windowPoints = count ? planningWindow(count, page) : null;
  const features = useMemo(
    () => (geo ? routeFeatures(geo.geometry) : []),
    [geo],
  );
  const landParts =
    features.find(
      (f: any) =>
        f.properties.route_id === selectedPipeline &&
        f.properties.segment === "land",
    )?.geometry.coordinates || [];
  const fit = (positions: Position[], maxZoom = 10) => {
    const m = map.current;
    if (!m || !positions.length) return;
    const bounds = new maplibregl.LngLatBounds(positions[0], positions[0]);
    positions.forEach((p) => bounds.extend(p));
    m.fitBounds(bounds, {
      padding: { top: 65, bottom: 100, left: 50, right: 50 },
      maxZoom,
      duration: duration(),
    });
  };
  const reset = () => {
    if (route)
      fit(
        features
          .filter((f: any) => f.properties.route_id === route.id)
          .flatMap((f: any) => f.geometry.coordinates.flat()),
      );
    else
      map.current?.fitBounds(COUNTRY_BOUNDS, {
        padding: 35,
        duration: duration(),
      });
  };

  useEffect(() => {
    if (!host.current) return;
    let cancelled = false;
    setLoaded(false);
    setError("");
    setTileError(false);
    priorRoute.current = null;
    fetch("/saudi-boundary.geojson")
      .then((r) => {
        if (!r.ok) throw Error("boundary");
        return r.json();
      })
      .then((boundary) => {
        if (cancelled || !host.current) return;
        setGeo(boundary);
        const outside = {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [30, 14],
                [60, 14],
                [60, 35],
                [30, 35],
                [30, 14],
              ],
              ...polygons(boundary.geometry).map((p) => [...p[0]].reverse()),
            ],
          },
        };
        const m = new maplibregl.Map({
          container: host.current,
          center: [44.7, 24.3],
          zoom: 5,
          minZoom: 4,
          maxZoom: 17,
          maxBounds: [
            [32, 14.5],
            [58.5, 34.5],
          ],
          renderWorldCopies: false,
          attributionControl: false,
          locale: {
            "NavigationControl.ZoomIn": "تكبير الخريطة",
            "NavigationControl.ZoomOut": "تصغير الخريطة",
            "AttributionControl.ToggleAttribution": "عرض مصادر الخريطة",
            "Popup.Close": "إغلاق قائمة المرافق",
          },
          dragRotate: false,
          pitchWithRotate: false,
          canvasContextAttributes: { preserveDrawingBuffer: true },
          style: {
            version: 8,
            sources: {
              satellite: {
                type: "raster",
                tiles: [imagery],
                tileSize: 256,
                maxzoom: 19,
                attribution:
                  "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
              },
              saudi: { type: "geojson", data: boundary },
              outside: { type: "geojson", data: outside as any },
              routes: { type: "geojson", data: empty as any },
              planning: { type: "geojson", data: empty as any },
            },
            layers: [
              {
                id: "background",
                type: "background",
                paint: { "background-color": "#283337" },
              },
              {
                id: "imagery",
                type: "raster",
                source: "satellite",
                paint: {
                  "raster-saturation": -0.15,
                  "raster-brightness-max": 0.82,
                },
              },
              {
                id: "outside-mask",
                type: "fill",
                source: "outside",
                paint: { "fill-color": "#141c28", "fill-opacity": 0.48 },
              },
              {
                id: "saudi-border",
                type: "line",
                source: "saudi",
                paint: {
                  "line-color": "#F1E8D6",
                  "line-opacity": 0.8,
                  "line-width": 1.2,
                },
              },
              {
                id: "route-halo",
                type: "line",
                source: "routes",
                filter: ["all", ["==", ["get", "segment"], "land"], ["!=", ["get", "route_id"], "P-8"]],
                layout: { "line-cap": "round", "line-join": "round" },
                paint: {
                  "line-color": "#202430",
                  "line-width": pipeWidth("", 1.8),
                  "line-opacity": 0.75,
                },
              },
              {
                id: "land-routes",
                type: "line",
                source: "routes",
                filter: [
                  "all",
                  ["==", ["get", "segment"], "land"],
                  ["!=", ["get", "route_id"], "P-8"],
                ],
                layout: { "line-cap": "round", "line-join": "round" },
                paint: {
                  "line-color": ["get", "color"],
                  "line-width": pipeWidth(),
                  "line-opacity": 0.95,
                },
              },
              {
                id: "historical-routes",
                type: "line",
                source: "routes",
                filter: ["==", ["get", "route_id"], "P-8"],
                layout: { "line-cap": "round", "line-join": "round" },
                paint: {
                  "line-color": "#BBC4D4",
                  "line-width": 2.5,
                  "line-dasharray": [4, 3],
                },
              },
              {
                id: "marine-routes",
                type: "line",
                source: "routes",
                filter: ["==", ["get", "segment"], "sea"],
                layout: { "line-cap": "round", "line-join": "round" },
                paint: {
                  "line-color": "#83D8FF",
                  "line-width": pipeWidth(),
                },
              },
              {
                id: "route-hit",
                type: "line",
                source: "routes",
                paint: { "line-width": 18, "line-opacity": 0 },
              },
              {
                id: "proposed-points",
                type: "circle",
                source: "planning",
                paint: {
                  "circle-radius": 5,
                  "circle-color": "#2B3348",
                  "circle-stroke-color": "#F9D3EF",
                  "circle-stroke-width": 2,
                },
              },
              {
                id: "selected-proposal",
                type: "circle",
                source: "planning",
                filter: ["==", ["get", "meters"], -1],
                paint: {
                  "circle-radius": 7,
                  "circle-color": "#F280A4",
                  "circle-stroke-color": "#FFFFFF",
                  "circle-stroke-width": 2,
                },
              },
            ],
          },
        });
        map.current = m;
        m.addControl(
          new maplibregl.NavigationControl({ showCompass: false }),
          "top-left",
        );
        m.addControl(
          new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }),
          "bottom-left",
        );
        m.addControl(
          new maplibregl.AttributionControl({ compact: true }),
          "bottom-left",
        );
        m.touchZoomRotate.disableRotation();
        m.on("error", (e) => {
          if (
            (e as any).sourceId === "satellite" ||
            e.error?.message?.includes("arcgisonline")
          )
            setTileError(true);
        });
        m.on("sourcedata", (e) => {
          if (e.sourceId === "satellite" && e.isSourceLoaded)
            setTileError(false);
        });
        m.on("zoomend", () => setZoom(m.getZoom()));
        m.on("moveend", () => setViewRevision(value => value + 1));
        m.on("resize", () => setViewRevision(value => value + 1));
        m.on("load", () => {
          if (cancelled) return;
          for (const material of ["oil", "gas", "sea"] as const) {
            m.addImage(`pipe-${material}`, createPipeTexture(material));
          }
          m.setPaintProperty("land-routes", "line-pattern", ["get", "texture"]);
          m.setPaintProperty("marine-routes", "line-pattern", "pipe-sea");
          m.fitBounds(COUNTRY_BOUNDS, { padding: 35, duration: 0 });
          setZoom(m.getZoom());
          setLoaded(true);
        });
        m.on("click", "route-hit", (e) => {
          if ((e.originalEvent.target as Element)?.closest?.(".maplibregl-popup, .maplibregl-marker")) return;
          const id = e.features?.[0]?.properties?.route_id;
          if (id) current.current.onPipelineSelect(id);
        });
        m.on(
          "mouseenter",
          "route-hit",
          () => (m.getCanvas().style.cursor = "pointer"),
        );
        m.on(
          "mouseleave",
          "route-hit",
          () => (m.getCanvas().style.cursor = ""),
        );
        m.on("click", "proposed-points", (e) => {
          const meters = e.features?.[0]?.properties?.meters;
          if (meters !== undefined) setPoint(Number(meters));
        });
      })
      .catch(() => {
        if (!cancelled) setError("تعذر فتح الخريطة. أعد المحاولة.");
      });
    return () => {
      cancelled = true;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      clusterPopup.current?.remove();
      map.current?.remove();
      map.current = null;
    };
  }, [retry]);

  useEffect(() => {
    const m = map.current;
    if (!loaded || !m || !geo) return;
    const visible = features
      .filter((f: any) => {
        const p = pipelines.find((p: any) => p.id === f.properties.route_id);
        return (
          p &&
          (p.lifecycle !== "decommissioned" ||
            history ||
            p.id === selectedPipeline)
        );
      })
      .map((f: any) => {
        const p = pipelines.find((p: any) => p.id === f.properties.route_id);
        return {
          ...f,
          properties: {
            ...f.properties,
            texture: p.medium === "gas" ? "pipe-gas" : "pipe-oil",
            color:
              p.lifecycle === "decommissioned"
                ? "#BBC4D4"
                : p.medium === "gas"
                  ? "#68DBAF"
                  : "#F3B78E",
          },
        };
      });
    (m.getSource("routes") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: visible,
    });
    const opacity = selectedPipeline
      ? ["case", ["==", ["get", "route_id"], selectedPipeline], 1, 0.28]
      : 0.95;
    m.setPaintProperty("land-routes", "line-width", pipeWidth(selectedPipeline));
    m.setPaintProperty("marine-routes", "line-width", pipeWidth(selectedPipeline));
    m.setPaintProperty("route-halo", "line-width", pipeWidth(selectedPipeline, 1.8));
    m.setPaintProperty("land-routes", "line-opacity", opacity);
    m.setPaintProperty("marine-routes", "line-opacity", opacity);
    m.setPaintProperty("historical-routes", "line-opacity", opacity);
    m.setPaintProperty(
      "route-halo",
      "line-opacity",
      selectedPipeline
        ? ["case", ["==", ["get", "route_id"], selectedPipeline], 0.9, 0.25]
        : 0.75,
    );
    if (priorRoute.current !== selectedPipeline) {
      priorRoute.current = selectedPipeline;
      if (selectedPipeline)
        fit(
          visible
            .filter((f: any) => f.properties.route_id === selectedPipeline)
            .flatMap((f: any) => f.geometry.coordinates.flat()),
        );
      else reset();
    }
  }, [loaded, geo, pipelines, selectedPipeline, history]);

  useEffect(() => {
    const m = map.current;
    if (!loaded || !m || !geo) return;
    markers.current.forEach((marker) => marker.remove());
    markers.current = [];
    clusterPopup.current?.remove();
    const container = m.getContainer();
    const bounds = { width: container.clientWidth, height: container.clientHeight };
    const viewport = container.getBoundingClientRect();
    const occupied: ScreenBox[] = [];
    container.closest(".satellite-view")?.querySelectorAll(
      ".satellite-legend, .geo-layer-controls, .geo-reset, .maplibregl-ctrl-top-left, .maplibregl-ctrl-bottom-left, .geo-tile-error",
    ).forEach(element => {
      const r = element.getBoundingClientRect();
      if (r.width && r.height) occupied.push({ x: r.left - viewport.left + r.width / 2, y: r.top - viewport.top + r.height / 2, width: r.width, height: r.height });
    });
    const onScreen = (p: ScreenPoint) => p.x >= -45 && p.x <= bounds.width + 45 && p.y >= -45 && p.y <= bounds.height + 45;
    const addMarker = (el: HTMLButtonElement, coordinates: Position, position: ScreenPoint, width: number, height: number) => {
      const anchor = m.project(coordinates);
      const dx = position.x - anchor.x, dy = position.y - anchor.y;
      const distance = Math.hypot(dx, dy);
      if (distance > 8) {
        const nx = -dx / distance, ny = -dy / distance;
        const edge = Math.min(width / 2 / Math.abs(nx || 1e-8), height / 2 / Math.abs(ny || 1e-8)) + 2;
        if (distance > edge) {
          const leader = document.createElement("span");
          leader.className = "map-marker-leader";
          leader.setAttribute("aria-hidden", "true");
          leader.style.left = `calc(50% + ${nx * edge}px)`;
          leader.style.top = `calc(50% + ${ny * edge}px)`;
          leader.style.width = `${distance - edge}px`;
          leader.style.transform = `rotate(${Math.atan2(ny, nx)}rad)`;
          el.append(leader);
          const dot = document.createElement("span");
          dot.className = "map-marker-anchor";
          dot.setAttribute("aria-hidden", "true");
          dot.style.left = `calc(50% - ${dx}px)`;
          dot.style.top = `calc(50% - ${dy}px)`;
          el.append(dot);
        }
      }
      markers.current.push(new maplibregl.Marker({ element: el, anchor: "center", offset: [dx, dy] }).setLngLat(coordinates).addTo(m));
    };
    const visibleSaddles = [...saddles].sort((a: any, b: any) =>
      Number(active(b.id)) - Number(active(a.id)) || Number(b.id === selected) - Number(a.id === selected) || a.id.localeCompare(b.id),
    );
    for (const s of visibleSaddles) {
      if (
        !Number.isFinite(s.lon) ||
        !Number.isFinite(s.lat) ||
        !inBoundary(displayPosition(s), geo.geometry)
      )
        continue;
      if (selectedPipeline && s.pipeline_id !== selectedPipeline) continue;
      if (onlyAlerts && !active(s.id)) continue;
      const status = saddleStatus(s, alerts);
      if (!saddleVisible(status, zoom)) continue;
      const anchor = m.project(displayPosition(s));
      if (!onScreen(anchor)) continue;
      // Separate labels when needed; the radar and leader endpoint stay at GPS.
      const position = placeMarker(anchor, 70, 34, occupied, bounds);
      if (status === "alert") {
        const radar = document.createElement("span");
        radar.className = "saddle-radar";
        radar.dataset.saddleId = s.id;
        radar.setAttribute("aria-hidden", "true");
        radar.setAttribute("role", "presentation");
        radar.tabIndex = -1;
        radar.innerHTML = '<i></i><i></i>';
        markers.current.push(new maplibregl.Marker({ element: radar, anchor: "center" }).setLngLat(displayPosition(s)).addTo(m));
      }
      const el = document.createElement("button");
      el.type = "button";
      el.className = `geo-saddle ${status} ${selected === s.id ? "selected" : ""}`;
      el.dataset.saddleId = s.id;
      el.dataset.status = status;
      el.dataset.location = `${s.lon},${s.lat}`;
      el.setAttribute("aria-label", `فتح سجل ${s.name} · ${SADDLE_STATUS_LABELS[status]}`);
      const findings = alerts.filter((a: any) => a.saddle_id === s.id && ["new", "acknowledged"].includes(a.status)).map((a: any) => a.title);
      el.title = `${s.name} · ${SADDLE_STATUS_LABELS[status]}${findings.length ? ' · ' + [...new Set(findings)].join('، ') : ''}`;
      el.innerHTML = saddleIconSvg();
      const number = document.createElement("b");
      number.dir = "ltr";
      number.textContent = s.id;
      el.append(number);
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        current.current.onSelect(s.id);
      });
      addMarker(el, displayPosition(s), position, 70, 34);
    }
    const points = assets.filter((a: any) => Number.isFinite(a.lon) && Number.isFinite(a.lat))
      .map((a: any) => ({ record: a, point: m.project(displayPosition(a)) }))
      .filter((a: any) => onScreen(a.point));
    const groups = groupFacilities<any>(points, zoom);
    const labels: { el: HTMLButtonElement; record: any; position: ScreenPoint }[] = [];
    for (const group of groups.sort((a, b) => b.records.length - a.records.length)) {
      const a = group.records[0];
      const isCluster = group.records.length > 1;
      const coordinates = isCluster ? m.unproject([group.anchor.x, group.anchor.y]).toArray() : displayPosition(a);
      const width = isCluster ? 62 : 34;
      const position = placeMarker(group.anchor, width, 38, occupied, bounds);
      const el = document.createElement("button");
      el.type = "button";
      if (isCluster) {
        const gasCount = group.records.filter(a => a.type !== "refinery").length;
        const refineryCount = group.records.length - gasCount;
        const kind = !gasCount ? "refinery" : !refineryCount ? "gas" : "mixed";
        el.className = `facility-cluster ${kind} ${group.records.some(a => a.id === selected) ? "selected" : ""}`;
        el.setAttribute("aria-label", `تجمع ${n(group.records.length)} مرافق، غاز ${n(gasCount)} ومصافي ${n(refineryCount)}`);
        el.title = `غاز: ${n(gasCount)} · مصافي: ${n(refineryCount)} · اضغط لعرض المرافق`;
        el.dataset.members = JSON.stringify(group.records.map(a => a.id));
        el.dataset.facilityCount = String(group.records.length);
        el.innerHTML = facilityGroupSvg();
        const count = document.createElement("b");
        count.textContent = n(group.records.length);
        el.append(count);
        el.addEventListener("click", event => {
          event.stopPropagation();
          clusterPopup.current?.remove();
          const content = document.createElement("section");
          content.className = "facility-cluster-detail";
          content.addEventListener("click", event => event.stopPropagation());
          content.addEventListener("mousedown", event => event.stopPropagation());
          content.addEventListener("touchstart", event => event.stopPropagation());
          content.addEventListener("wheel", event => event.stopPropagation(), { passive: true });
          content.setAttribute("aria-label", "تفاصيل تجمع المرافق");
          const heading = document.createElement("h4");
          heading.textContent = `تجمع مرافق · ${n(group.records.length)}`;
          const summary = document.createElement("p");
          summary.textContent = `مرافق الغاز: ${n(gasCount)} · المصافي: ${n(refineryCount)}`;
          content.append(heading, summary);
          const list = document.createElement("div");
          list.className = "facility-cluster-members";
          for (const member of group.records) {
            const button = document.createElement("button");
            button.type = "button";
            button.setAttribute("aria-label", `فتح ${member.type === "refinery" ? "مصفاة" : "مرفق غاز"} ${member.name}`);
            button.innerHTML = facilityIconSvg(member.type);
            const name = document.createElement("span");
            name.textContent = member.name;
            button.append(name);
            button.addEventListener("click", () => { clusterPopup.current?.remove(); current.current.onSelect(member.id); });
            list.append(button);
          }
          const expand = document.createElement("button");
          expand.type = "button";
          expand.className = "facility-cluster-expand";
          expand.textContent = "تكبير المرافق على الخريطة";
          expand.addEventListener("click", () => { clusterPopup.current?.remove(); fit(group.records.map(displayPosition), 16); });
          content.append(expand, list);
          clusterPopup.current = new maplibregl.Popup({ closeOnMove: true, offset: 23, maxWidth: "260px", className: "facility-cluster-popup" })
            .setLngLat(m.unproject([position.x, position.y])).setDOMContent(content).addTo(m);
        });
      } else {
        const kind = a.type === "refinery" ? "refinery" : "gas";
        el.className = `facility-marker ${kind} ${selected === a.id ? "selected" : ""}`;
        el.setAttribute("aria-label", `${kind === "gas" ? "مرفق غاز" : "مصفاة"} ${a.name}`);
        el.title = `${a.name} · موقع تقريبي`;
        el.dataset.facilityId = a.id;
        el.innerHTML = facilityIconSvg(kind);
        const name = document.createElement("span");
        name.className = "facility-label";
        name.textContent = a.name;
        el.append(name);
        labels.push({ el, record: a, position });
        el.addEventListener("click", event => { event.stopPropagation(); current.current.onSelect(a.id); });
      }
      addMarker(el, coordinates, position, width, 38);
    }
    const measure = document.createElement("canvas").getContext("2d");
    if (measure) measure.font = '500 11px "IBM Plex Sans Arabic"';
    for (const item of labels.sort((a, b) => Number(b.record.id === selected) - Number(a.record.id === selected))) {
      if (!showNames || (zoom < 8.5 && item.record.id !== selected)) continue;
      const width = Math.min(160, (measure?.measureText(item.record.name).width || 80) + 16);
      const box = { x: item.position.x - 25 - width / 2, y: item.position.y, width, height: 24 };
      if (box.x - width / 2 < 5 || box.y - 12 < 5 || box.y + 12 > bounds.height - 5 || occupied.some(other => boxesOverlap(box, other, 3))) continue;
      item.el.classList.add("with-label");
      occupied.push(box);
    }
    if (selectedPipeline === "P-6") {
      const end = features
        .find((f: any) => f.properties.segment === "sea")
        ?.geometry.coordinates.at(-1)
        ?.at(-1);
      if (end) {
        const label = document.createElement("span");
        label.className = "marine-destination";
        label.textContent = "إلى البحرين";
        label.setAttribute("role", "img");
        label.setAttribute("aria-label", "وجهة المقطع البحري: البحرين");
        markers.current.push(
          new maplibregl.Marker({
            element: label,
            anchor: "right",
            offset: [-10, 0],
          })
            .setLngLat(end)
            .addTo(m),
        );
      }
    }
    if (priorSelection.current !== selected) {
      priorSelection.current = selected;
      const a = [...assets, ...saddles].find((a: any) => a.id === selected);
      if (a)
        m.easeTo({
          center: displayPosition(a),
          zoom: Math.max(selected.startsWith("S-") ? 8 : 11, m.getZoom()),
          duration: duration(),
        });
    }
  }, [
    loaded,
    geo,
    assets,
    saddles,
    selected,
    selectedPipeline,
    onlyAlerts,
    alerts,
    zoom,
    showNames,
    viewRevision,
  ]);

  useEffect(() => {
    setPage(0);
    setPoint(null);
    setPlanningView(false);
  }, [selectedPipeline]);
  useEffect(() => {
    const m = map.current;
    if (!loaded || !m) return;
    const points =
      windowPoints && planningLength
        ? windowPoints.points.flatMap((p) => {
            const xy = pointAlong(
              landParts,
              p.meters / (planningLength * 1000),
            );
            return xy
              ? [
                  {
                    type: "Feature",
                    properties: { meters: p.meters, index: p.index },
                    geometry: { type: "Point", coordinates: xy },
                  },
                ]
              : [];
          })
        : [];
    (m.getSource("planning") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: points,
    } as any);
    m.setFilter("selected-proposal", ["==", ["get", "meters"], point ?? -1]);
    if (planningView && points.length)
      fit(
        points.map((p) => p.geometry.coordinates),
        16,
      );
  }, [
    loaded,
    selectedPipeline,
    geo,
    page,
    planningLength,
    point,
    planningView,
  ]);
  const zoomPlanning = () => {
    if (!windowPoints || !planningLength) return;
    const points = windowPoints.points
      .map((p) => pointAlong(landParts, p.meters / (planningLength * 1000)))
      .filter(Boolean) as Position[];
    setPlanningView(true);
    fit(points, 16);
  };

  return (
    <section
      className="geo-workspace"
      aria-label="خريطة خطوط الأنابيب بالأقمار الصناعية"
    >
      <div className="geo-heading">
        <div>
          <Satellite size={20} />
          <strong>
            {route ? route.name : "شبكة الخطوط · المملكة العربية السعودية"}
          </strong>
        </div>
        {route ? (
          <button onClick={() => onPipelineSelect("")}>
            <ArrowRight size={15} />
            عرض المملكة
          </button>
        ) : (
          <span className="satellite-tag">Satellite · أقمار صناعية</span>
        )}
      </div>
      {route && (
        <div className="geo-route-summary">
          <span>
            <strong>{n(registered.length)}</strong> أسرجة مسجلة
          </span>
          <span>
            <strong>{count === null ? "—" : n(count)}</strong> نقاط تخطيط مقترحة
          </span>
          <span>
            {route.lifecycle === "decommissioned"
              ? "خط تاريخي متوقف"
              : route.id === "P-6"
                ? "الجزء السعودي + المقطع البحري"
                : "مسار تقريبي"}
          </span>
        </div>
      )}
      <div className="satellite-view">
        <div
          ref={host}
          className="satellite-canvas"
          aria-label="خريطة تفاعلية؛ استخدم أزرار التكبير أو اسحب لتحريك الخريطة"
        />
        {!loaded && !error && (
          <div className="geo-loading" role="status">
            جارٍ فتح الخريطة…
          </div>
        )}
        {error && (
          <div className="geo-loading" role="alert">
            {error}
            <button onClick={() => setRetry(retry + 1)}>إعادة المحاولة</button>
          </div>
        )}
        {tileError && (
          <div className="geo-tile-error" role="status">
            تعذر تحميل بعض صور الأقمار الصناعية. تحقق من الإنترنت.
            <button onClick={() => setRetry(retry + 1)}>إعادة المحاولة</button>
          </div>
        )}
        <button
          className="geo-reset"
          aria-label="إعادة ضبط الخريطة"
          onClick={reset}
        >
          <LocateFixed size={18} />
        </button>
        {selectedSaddle && <button
          className="geo-reset geo-saddle-focus"
          aria-label={`الاقتراب من ${selectedSaddle.name}`}
          title={`الاقتراب من ${selectedSaddle.name}`}
          onClick={() => map.current?.easeTo({ center: displayPosition(selectedSaddle), zoom: Math.max(8.5, map.current.getZoom()), duration: duration() })}
        ><Radio size={18} /></button>}
        <div className="geo-layer-controls">
          <label>
            <input
              type="checkbox"
              checked={showNames}
              onChange={(e) => setShowNames(e.target.checked)}
            />
            أسماء المرافق عند التكبير
          </label>
          <label>
            <input
              type="checkbox"
              checked={history}
              onChange={(e) => setHistory(e.target.checked)}
            />
            الخطوط التاريخية
          </label>
        </div>
        <div className="satellite-legend" aria-label="مفتاح الخريطة">
          <strong>مفتاح الخريطة</strong>
          <span>
            <FacilityIcon type="gas" size={22} />
            مرفق غاز
          </span>
          <span>
            <FacilityIcon type="refinery" size={22} />
            مصفاة
          </span>
          <span>
            <i className="geo-line oil" />
            نفط · بري
          </span>
          <span>
            <i className="geo-line gas" />
            غاز · بري
          </span>
          <span>
            <i className="geo-line marine" />
            مقطع بحري
          </span>
          <span><i className="saddle-key healthy"><svg viewBox="0 0 32 30" aria-hidden="true" dangerouslySetInnerHTML={{ __html: SADDLE_ICON_BODY }} /></i>سرج سليم</span>
          <span><i className="saddle-key alert"><svg viewBox="0 0 32 30" aria-hidden="true" dangerouslySetInnerHTML={{ __html: SADDLE_ICON_BODY }} /></i>سرج به تنبيه</span>
          <span><i className="saddle-key unknown"><svg viewBox="0 0 32 30" aria-hidden="true" dangerouslySetInnerHTML={{ __html: SADDLE_ICON_BODY }} /></i>بانتظار القراءات</span>
          <span>
            <Layers2 size={19} color="#535DC2" />
            تجمع مرافق
          </span>
          {(history || route?.lifecycle === "decommissioned") && (
            <span>
              <i className="geo-line historical" />
              تاريخي متوقف
            </span>
          )}
        </div>
      </div>
      {route ? (
        <div className="route-information">
          <div className="geo-registered">
            <strong>الأسرجة المسجلة على الخط</strong>
            {registered
              .filter((s: any) => !onlyAlerts || active(s.id))
              .map((s: any) => (
                <button key={s.id} onClick={() => onSelect(s.id)}>
                  <Radio size={14} />
                  {s.name}
                </button>
              ))}
            {!registered.length && <span>لا توجد أسرجة مسجلة بعد.</span>}
            {registered.length > 0 &&
              onlyAlerts &&
              !registered.some((s: any) => active(s.id)) && (
                <span>لا توجد أسرجة ذات تنبيه جديد.</span>
              )}
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
                    ? "طول منشور؛ المواضع الجغرافية تقريبية"
                    : "لم يتوفر طول موثق؛ لا يُحسب عدد افتراضي"}
              </small>
            </label>
          )}
          {windowPoints && (
            <div className="planning-pagination">
              <button
                aria-label="نقاط التخطيط السابقة"
                disabled={windowPoints.page === 0}
                onClick={() => {
                  setPage(windowPoints.page - 1);
                  setPoint(null);
                }}
              >
                <ChevronRight size={17} />
              </button>
              <span>
                النقاط {n(windowPoints.points[0].index)}–
                {n(windowPoints.points.at(-1)!.index)} من {n(count!)}
                <small>كل 31 م · نقاط مقترحة؛ ليست مواقع أجهزة مثبتة</small>
              </span>
              <button
                aria-label="نقاط التخطيط التالية"
                disabled={windowPoints.page + 1 === windowPoints.pages}
                onClick={() => {
                  setPage(windowPoints.page + 1);
                  setPoint(null);
                }}
              >
                <ChevronLeft size={17} />
              </button>
              <button onClick={zoomPlanning}>
                <LocateFixed size={15} />
                تكبير نقاط التخطيط
              </button>
              <label>
                نقطة تخطيط
                <select
                  aria-label="اختيار نقطة تخطيط"
                  value={point ?? ""}
                  onChange={(e) =>
                    setPoint(
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                >
                  <option value="">اختر نقطة</option>
                  {windowPoints.points.map((p) => (
                    <option key={p.index} value={p.meters}>
                      {n(p.index)} · {n(p.meters)} م
                    </option>
                  ))}
                </select>
              </label>
              <label>
                نافذة رقم
                <input
                  aria-label="نافذة نقاط التخطيط"
                  type="number"
                  min="1"
                  max={windowPoints.pages}
                  value={windowPoints.page + 1}
                  onChange={(e) => {
                    setPage(
                      Math.max(
                        0,
                        Math.min(
                          windowPoints.pages - 1,
                          Number(e.target.value) - 1,
                        ),
                      ),
                    );
                    setPoint(null);
                  }}
                />
              </label>
            </div>
          )}
          {point !== null && (
            <p className="geo-planning-selection">
              نقطة مقترحة عند {n(point)} م؛ لا يوجد جهاز أو سجل قياس.
            </p>
          )}
          {route.id === "P-6" && (
            <p className="marine-note">
              <Waves size={17} />
              AB-4: المقطع البحري 42 كم وفق أرامكو. العدد المقترح محسوب على
              الجزء البري السعودي البالغ 42 كم فقط.
            </p>
          )}
          <p>
            {route.id === "P-6"
              ? "يُعرض الاتصال البحري إلى البحرين؛ رسم المقطع تقريبي وليس إحداثيات تشغيلية."
              : route.source === "illustrative_route"
                ? "مسار مقترح؛ المحاذاة الجغرافية تقريبية."
                : route.lifecycle === "decommissioned"
                  ? "مسار تاريخي متوقف؛ مستبعد من تخطيط المراقبة."
                  : "وجهات الخط موثقة؛ المحاذاة بين الوجهات تقريبية وتحتاج بيانات GIS من المالك للتحقق التفصيلي."}
          </p>
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
        <div className="geo-route-index">
          {pipelines
            .filter((p: any) => history || p.lifecycle !== "decommissioned")
            .map((p: any) => (
              <button key={p.id} onClick={() => onPipelineSelect(p.id)}>
                <i className={p.medium === "gas" ? "gas" : "oil"} />
                <strong>{p.name}</strong>
                <span>
                  {n(saddles.filter((s: any) => s.pipeline_id === p.id).length)}{" "}
                  أسرجة مسجلة
                </span>
                <ChevronLeft size={15} />
              </button>
            ))}
        </div>
      )}
      <p className="geo-note">
        مواقع المرافق ومسارات الربط تقريبية. المقاطع البرية داخل حدود المملكة،
        والمقاطع البحرية موضحة بالأزرق المتقطع. صور الأقمار الصناعية تحتاج
        اتصالًا بالإنترنت.
      </p>
    </section>
  );
}
