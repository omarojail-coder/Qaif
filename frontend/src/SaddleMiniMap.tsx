import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as GLMap, type GeoJSONSource } from "maplibre-gl";
import { LocateFixed } from "lucide-react";
import type { RecordData } from "./api";
import { displayPosition } from "./mapLocations";
import { routeFeatures } from "./geoRoutes";
import { createPipeTexture } from "./pipeTexture";
import { saddleStatus, saddleIconSvg, SADDLE_STATUS_LABELS } from "./saddleMarkers";
import { DISPLAY_LOCALE } from "./locale";
import "maplibre-gl/dist/maplibre-gl.css";
import "./saddle-minimap.css";

const empty = { type: "FeatureCollection", features: [] } as const;
const CLOSE_ZOOM = 13;

export default function SaddleMiniMap({ saddle, pipeline, alerts }: {
  saddle: RecordData;
  pipeline?: RecordData;
  alerts: RecordData[];
}) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<GLMap | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);
  const current = useRef(saddle);
  current.current = saddle;
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [geometry, setGeometry] = useState<any>(null);
  const position = displayPosition(saddle);
  const valid = Number.isFinite(position[0]) && Number.isFinite(position[1]) &&
    Math.abs(position[0]) <= 180 && Math.abs(position[1]) <= 90;
  const status = saddleStatus(saddle, alerts);

  useEffect(() => {
    if (!host.current || !valid) return;
    let alive = true;
    const abort = new AbortController();
    let resize: ResizeObserver | undefined;
    let instance: GLMap | undefined;
    setFailed(false);
    setReady(false);
    try {
      instance = new maplibregl.Map({
        container: host.current,
        center: displayPosition(current.current),
        zoom: CLOSE_ZOOM, minZoom: 6, maxZoom: 17,
        renderWorldCopies: false, attributionControl: false,
        scrollZoom: false, dragRotate: false, pitchWithRotate: false,
        canvasContextAttributes: { preserveDrawingBuffer: true },
        locale: {
          "NavigationControl.ZoomIn": "تكبير موقع السرج",
          "NavigationControl.ZoomOut": "تصغير موقع السرج",
          "AttributionControl.ToggleAttribution": "عرض مصادر الخريطة المصغرة",
        },
        style: {
          version: 8,
          sources: {
            satellite: {
              type: "raster", tileSize: 256, maxzoom: 19,
              tiles: ["https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
              attribution: "Source: Esri, Vantor, Earthstar Geographics, GIS User Community",
            },
            route: { type: "geojson", data: empty as any },
          },
          layers: [
            { id: "background", type: "background", paint: { "background-color": "#283337" } },
            { id: "imagery", type: "raster", source: "satellite", paint: { "raster-saturation": -0.15, "raster-brightness-max": 0.82 } },
            { id: "pipe-casing", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#202430", "line-width": 10, "line-opacity": 0.85 } },
            { id: "pipe", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#e5a26e", "line-width": 7 } },
          ],
        },
      });
      map.current = instance;
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
      instance.addControl(new maplibregl.ScaleControl({ maxWidth: 65, unit: "metric" }), "bottom-left");
      instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
      instance.touchZoomRotate.disableRotation();
      const canvas = instance.getCanvas();
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `خريطة قريبة لموقع ${current.current.name}`);
      instance.on("load", () => {
        if (!alive || !instance) return;
        for (const material of ["oil", "gas", "sea"] as const)
          instance.addImage(`mini-pipe-${material}`, createPipeTexture(material));
        setReady(true);
      });
      instance.on("error", (event) => {
        if (alive && ((event as any).sourceId === "satellite" || event.error?.message.includes("arcgisonline"))) setTileError(true);
      });
      instance.on("sourcedata", (event) => {
        if (alive && event.sourceId === "satellite" && event.isSourceLoaded) setTileError(false);
      });
      resize = new ResizeObserver(() => instance?.resize());
      resize.observe(host.current);
      fetch("/saudi-boundary.geojson", { signal: abort.signal })
        .then(response => { if (!response.ok) throw new Error("boundary"); return response.json(); })
        .then(boundary => { if (alive) setGeometry(boundary.geometry); })
        .catch(() => {}); // The location marker remains usable if route geometry is unavailable.
    } catch {
      setFailed(true);
    }
    return () => {
      alive = false;
      abort.abort();
      resize?.disconnect();
      marker.current?.remove();
      marker.current = null;
      instance?.remove();
      map.current = null;
    };
  }, [valid]);

  // Changing saddles recenters; incoming reading/alert updates do not reset a user's pan or zoom.
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance || !valid) return;
    instance.jumpTo({ center: position, zoom: CLOSE_ZOOM });
    instance.getCanvas().setAttribute("aria-label", `خريطة قريبة لموقع ${saddle.name}`);
  }, [ready, valid, saddle.id, position[0], position[1]]);

  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance || !valid) return;
    marker.current?.remove();
    const patch = document.createElement("span");
    patch.className = `mini-patch ${status}`;
    patch.dataset.saddleId = saddle.id;
    patch.dataset.status = status;
    patch.dataset.location = position.join(",");
    patch.setAttribute("role", "img");
    patch.setAttribute("aria-label", `${saddle.id} · ${SADDLE_STATUS_LABELS[status]}`);
    patch.innerHTML = saddleIconSvg();
    const id = document.createElement("b");
    id.dir = "ltr";
    id.textContent = saddle.id;
    patch.append(id);
    marker.current = new maplibregl.Marker({ element: patch, anchor: "center" }).setLngLat(position).addTo(instance);
    const features = geometry ? routeFeatures(geometry).filter(f => f.properties.route_id === saddle.pipeline_id) : [];
    (instance.getSource("route") as GeoJSONSource).setData({ type: "FeatureCollection", features } as any);
    const gas = String(pipeline?.medium || "").includes("gas") || String(pipeline?.kind || "").includes("gas") || String(pipeline?.name || "").includes("غاز");
    instance.setPaintProperty("pipe", "line-pattern", ["case", ["==", ["get", "segment"], "sea"], "mini-pipe-sea", gas ? "mini-pipe-gas" : "mini-pipe-oil"]);
  }, [ready, valid, geometry, saddle.id, saddle.pipeline_id, position[0], position[1], status, pipeline?.name, pipeline?.medium, pipeline?.kind]);

  const coordinate = (value: number) => value.toLocaleString(DISPLAY_LOCALE, { maximumFractionDigits: 5 });
  return (
    <div className="saddle-mini" data-saddle-id={saddle.id} data-location={position.join(",")}>
      <div className="saddle-mini-frame">
        <div ref={host} className="saddle-mini-map" role="region" aria-label={`الخريطة المصغرة · ${saddle.name}`} />
        {valid && !failed && <button className="saddle-mini-reset" title="إعادة التركيز على السرج" aria-label="إعادة التركيز على السرج"
          onClick={() => map.current?.jumpTo({ center: position, zoom: CLOSE_ZOOM })}><LocateFixed size={16} /></button>}
        {(!valid || failed) && <p className="saddle-mini-message" role="status">{valid ? "تعذر عرض الخريطة." : "موقع السرج غير متوفر."}</p>}
        {tileError && <p className="saddle-mini-tile-note" role="status">تعذر تحميل صور الأقمار الصناعية.</p>}
      </div>
      <div className="saddle-mini-caption"><strong dir="ltr">{saddle.id}</strong><span className={`mini-status ${status}`}>{SADDLE_STATUS_LABELS[status]}</span></div>
      {pipeline && <p className="saddle-mini-route">{pipeline.name}</p>}
      {valid && <p className="saddle-mini-coordinates" dir="ltr">{coordinate(position[1])} N · {coordinate(position[0])} E</p>}
    </div>
  );
}
