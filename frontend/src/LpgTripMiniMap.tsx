import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as GLMap, type GeoJSONSource } from 'maplibre-gl';
import { LocateFixed, MapPin } from 'lucide-react';
import { flightPoint, travelledPath } from './droneFlight';
import { STATIONS, STATION_SVG, TRUCK_SVG, type ShipmentTrip } from './lpgMapData';
import './drone-flight.css';

const line = (coordinates: number[][]) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates } }) as const;

export default function LpgTripMiniMap({ trip, progress }: { trip: ShipmentTrip; progress: number }) {
  const host = useRef<HTMLDivElement>(null), map = useRef<GLMap | null>(null);
  const vehicle = useRef<maplibregl.Marker | null>(null);
  const [ready, setReady] = useState(false), [error, setError] = useState(''), [tileError, setTileError] = useState(false);
  const [retry, setRetry] = useState(0);
  const station = STATIONS.find(s => s.id === trip.stationId)!;
  const fit = () => {
    const bounds = new maplibregl.LngLatBounds(trip.path[0], trip.path[0]);
    trip.path.forEach(p => bounds.extend(p));
    map.current?.fitBounds(bounds, { padding: { top: 54, bottom: 50, left: 45, right: 45 }, maxZoom: 13, duration: 0 });
  };
  useEffect(() => {
    if (!host.current) return;
    let alive = true, instance: GLMap | undefined, observer: ResizeObserver | undefined;
    const markers: maplibregl.Marker[] = [];
    setReady(false); setError(''); setTileError(false);
    try {
      instance = new maplibregl.Map({
        container: host.current, center: trip.path[0], zoom: 8, minZoom: 3, maxZoom: 17,
        renderWorldCopies: false, attributionControl: false, scrollZoom: false, dragRotate: false, pitchWithRotate: false,
        canvasContextAttributes: { preserveDrawingBuffer: true },
        locale: { 'NavigationControl.ZoomIn': 'تكبير مسار الشحنة', 'NavigationControl.ZoomOut': 'تصغير مسار الشحنة', 'AttributionControl.ToggleAttribution': 'مصادر الخريطة' },
        style: { version: 8, sources: {
          satellite: { type: 'raster', tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 19, attribution: 'Imagery: Esri, Vantor, Earthstar Geographics' },
          route: { type: 'geojson', data: line(trip.path) },
          covered: { type: 'geojson', data: line([trip.path[0], trip.path[0]]) },
        }, layers: [
          { id: 'background', type: 'background', paint: { 'background-color': '#283337' } },
          { id: 'imagery', type: 'raster', source: 'satellite', paint: { 'raster-saturation': -.2, 'raster-brightness-max': .85 } },
          { id: 'route-halo', type: 'line', source: 'route', paint: { 'line-color': '#fff', 'line-width': 6, 'line-opacity': .75 } },
          { id: 'route-plan', type: 'line', source: 'route', paint: { 'line-color': '#b7bdfb', 'line-width': 3, 'line-dasharray': [3, 2] } },
          { id: 'route-covered', type: 'line', source: 'covered', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': trip.status === 'alert' ? '#a54459' : '#6772e8', 'line-width': 4 } },
        ] },
      });
      map.current = instance;
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
      instance.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      instance.touchZoomRotate.disableRotation();
      instance.getCanvas().setAttribute('role', 'img');
      instance.getCanvas().setAttribute('aria-label', `مسار ${trip.saddleId} من ${station.name} إلى ${trip.destination.city}`);
      fit();
      instance.on('load', () => { if (alive) setReady(true); });
      instance.on('error', event => { if (alive && (event as any).sourceId === 'satellite') setTileError(true); });
      instance.on('sourcedata', event => { if (alive && event.sourceId === 'satellite' && event.isSourceLoaded) setTileError(false); });
      const endpoint = (position: [number, number], icon: string, label: string, className: string) => {
        const element = document.createElement('span'); element.className = `shipment-endpoint ${className}`;
        element.innerHTML = icon; element.title = label;
        element.setAttribute('role', 'img'); element.setAttribute('aria-label', label);
        markers.push(new maplibregl.Marker({ element, anchor: 'bottom' }).setLngLat(position).addTo(instance!));
      };
      endpoint(trip.path[0], STATION_SVG, station.name, 'origin');
      endpoint(trip.path[trip.path.length - 1], '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 10h18l-2-6H5l-2 6Zm1 0v11h16V10M9 21v-7h6v7M3 10v2h18v-2"/></svg>', trip.destination.name, 'target');
      const icon = document.createElement('span'); icon.className = `shipment-moving ${trip.status}`;
      icon.innerHTML = TRUCK_SVG;
      const label = document.createElement('b'); label.dir = 'ltr'; label.textContent = trip.saddleId; icon.append(label);
      icon.setAttribute('role', 'img'); icon.setAttribute('aria-label', `موقع سراج الشحنة ${trip.saddleId}`);
      vehicle.current = new maplibregl.Marker({ element: icon }).setLngLat(flightPoint(trip.path, progress)).addTo(instance);
      observer = new ResizeObserver(() => { instance?.resize(); fit(); }); observer.observe(host.current);
    } catch { setError('تعذر عرض خريطة الرحلة.'); }
    return () => { alive = false; observer?.disconnect(); markers.forEach(m => m.remove()); vehicle.current?.remove(); vehicle.current = null; instance?.remove(); map.current = null; };
  }, [trip.id, retry]);
  useEffect(() => {
    if (!ready || !map.current) return;
    const point = flightPoint(trip.path, progress);
    vehicle.current?.setLngLat(point);
    const element = vehicle.current?.getElement();
    if (element) { element.dataset.position = point.join(','); element.dataset.progress = String(progress); }
    (map.current.getSource('covered') as GeoJSONSource)?.setData(line(travelledPath(trip.path, progress)));
  }, [ready, progress, trip.path]);
  return <section className="panel shipment-map-panel" aria-label="مسار سراج الشحنة">
    <div className="panel-heading"><h3><MapPin size={18}/>مسار الرحلة</h3><span>{progress >= 1 ? 'وصلت الشحنة' : 'في الطريق'}</span></div>
    <div className="drone-flight-frame">
      <div ref={host} className="drone-flight-map shipment-mini-map" role="region" aria-label="خريطة رحلة سراج الشحنة"/>
      <button className="flight-fit" aria-label="عرض مسار الشحنة كاملًا" onClick={fit}><LocateFixed size={17}/></button>
      {!ready && !error && <p className="flight-message" role="status">جاري تجهيز المسار…</p>}
      {error && <p className="flight-message" role="alert">{error}<button onClick={() => setRetry(v => v + 1)}>إعادة المحاولة</button></p>}
      {tileError && <p className="flight-tile-error" role="status">تعذر تحميل صور الأقمار؛ المسار متاح.</p>}
    </div>
    <div className="flight-endpoints"><div><span>الانطلاق</span><strong>{station.name}</strong></div><div><span>الوجهة</span><strong>{trip.destination.city}</strong></div></div>
    <div className="flight-progress"><span>تقدم الرحلة</span><strong dir="ltr">{Math.floor(progress * 100)}%</strong></div>
    <progress max="1" value={progress} aria-label="تقدم رحلة الشحنة"/>
  </section>;
}
