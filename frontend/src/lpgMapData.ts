import { inBoundary, type Boundary, type Position } from "./geoRoutes.ts";

export type Station = { id: string; name: string; region: string; service: string; color: string; position: Position; label: Position; cities: { name: string; position: Position }[] };
export type Store = { id: string; name: string; city: string; stationId: string; position: Position };
export type ShipmentTrip = { id: string; saddleId: string; stationId: string; truck: string; destination: Store; path: Position[]; status: "alert" | "healthy" | "unknown"; duration: number; initialProgress: number; source: "display_scenario"; viewProgress?: number; viewStartedMs?: number };
export const NETWORK_STORE_ESTIMATE = 1300;
const cities = (...rows: [string, number, number][]) => rows.map(([name, lon, lat]) => ({ name, position: [lon, lat] as Position }));

// Facility points represent the named cities, not surveyed GASCO installation coordinates.
// Service allocation and retailer locations are intentionally illustrative.
export const STATIONS: Station[] = [
  { id: "riyadh", name: "محطة الرياض", region: "المنطقة الوسطى", service: "الرياض ومحافظات المنطقة الوسطى", color: "#6772E8", position: [46.82, 24.55], label: [45.5, 23.6], cities: cities(["الرياض",46.72,24.68],["الخرج",47.32,24.15],["المجمعة",45.34,25.91],["الدوادمي",44.39,24.5],["وادي الدواسر",44.81,20.46],["القويعية",45.27,24.06],["عفيف",42.92,23.91]) },
  { id: "jeddah", name: "محطة جدة", region: "الساحل الغربي", service: "جدة ومكة ومدن الساحل الغربي", color: "#F280A4", position: [39.25,21.4], label: [39.06,22.55], cities: cities(["جدة",39.22,21.57],["مكة",39.84,21.42],["رابغ",39.05,22.8],["القنفذة",41.08,19.12],["الليث",40.28,20.15]) },
  { id: "dammam", name: "محطة الدمام", region: "المنطقة الشرقية", service: "الدمام ومحافظات المنطقة الشرقية", color: "#A98CF6", position: [49.98,26.36], label: [49.65,24.55], cities: cities(["الدمام",50.1,26.4],["الخبر",50.19,26.27],["الجبيل",49.62,27.01],["الأحساء",49.58,25.38],["حفر الباطن",45.96,28.43],["القطيف",50.01,26.54]) },
  { id: "madinah", name: "محطة المدينة المنورة", region: "المدينة والشمال الغربي", service: "المدينة ومناطق شمال غرب المملكة", color: "#FA965A", position: [39.68,24.53], label: [38.8,27.25], cities: cities(["المدينة المنورة",39.62,24.48],["ينبع",38.12,24.09],["العلا",37.92,26.61],["تبوك",36.57,28.38],["أملج",37.28,25.06],["سكاكا",40.2,29.97],["القريات",37.35,31.32]) },
  { id: "qassim", name: "محطة القصيم", region: "القصيم وشمال المملكة", service: "القصيم ومحافظات الشمال في توزيع العرض", color: "#D57B7D", position: [43.97,26.36], label: [43.2,28.25], cities: cities(["بريدة",43.97,26.36],["عنيزة",43.99,26.08],["الرس",43.5,25.87],["حائل",41.7,27.51],["عرعر",41.02,30.98],["رفحاء",43.49,29.63]) },
  { id: "taif", name: "محطة الطائف", region: "الطائف والمرتفعات الغربية", service: "الطائف والمراكز المحيطة والباحة في توزيع العرض", color: "#9470CA", position: [40.47,21.28], label: [41.2,21.1], cities: cities(["الطائف",40.43,21.28],["الحوية",40.5,21.46],["تربة",41.65,21.22],["رنية",42.85,21.26],["الباحة",41.47,20.01],["بلجرشي",41.56,19.86]) },
  { id: "abha", name: "محطة أبها", region: "المنطقة الجنوبية", service: "خميس مشيط وأبها ومحافظات الجنوب", color: "#8296C9", position: [42.73,18.3], label: [43.95,18.6], cities: cities(["خميس مشيط",42.73,18.3],["أبها",42.51,18.22],["جازان",42.59,16.91],["نجران",44.23,17.56],["بيشة",42.61,20.0],["صبيا",42.62,17.15]) },
];

export function ownerAt(position: Position, areas: any): string | null {
  return areas.features.find((f: any) => inBoundary(position, f.geometry))?.properties.station_id ?? null;
}

export function makeStores(boundary: Boundary, areas: any): Store[] {
  const stores: Store[] = [];
  for (const station of STATIONS) for (const city of station.cities) {
    for (let i = 0; i < 7; i++) {
      const angle = i * 2.39996323, radius = i === 0 ? 0 : 0.014 + 0.008 * Math.sqrt(i);
      const position: Position = [city.position[0] + Math.cos(angle)*radius, city.position[1] + Math.sin(angle)*radius];
      if (!inBoundary(position, boundary) || ownerAt(position, areas) !== station.id) continue;
      stores.push({ id: `SHOP-${String(stores.length+1).padStart(3,"0")}`, name: `متجر ${city.name} ${i+1}`, city: city.name, stationId: station.id, position });
    }
  }
  return stores;
}

export function makeTrips(stores: Store[], boundary: Boundary): ShipmentTrip[] {
  const trips: ShipmentTrip[] = [];
  for (const station of STATIONS) {
    const candidates = stores.filter(s => s.stationId === station.id);
    // Select destinations spread across separate towns; no optical scan or AI inference is claimed.
    const preferred = station.cities.slice(1,4).map(c => candidates.find(s => s.city === c.name)).filter(Boolean) as Store[];
    const targets = [...preferred];
    for (const candidate of candidates) {
      if (targets.length >= 3) break;
      if (!targets.some(t=>t.city===candidate.city)) targets.push(candidate);
    }
    targets.forEach((destination, offset) => {
      const path: Position[] = [];
      // A geographic display corridor, not a road routing service.
      for (let i=0; i<=24; i++) {
        const t=i/24;
        const inlandBend = station.id === "jeddah" ? Math.sin(Math.PI*t)*0.25 : 0;
        path.push([station.position[0]+(destination.position[0]-station.position[0])*t+inlandBend, station.position[1]+(destination.position[1]-station.position[1])*t]);
      }
      if (path.some(p=>!inBoundary(p,boundary))) return;
      const index = trips.length + 1;
      trips.push({ id: `TRIP-${String(index).padStart(3,"0")}`, saddleId: `S-${index}`, stationId: station.id, truck: `TRK-${String(100+index)}`, destination, path, status: [2,8,14,20].includes(index) ? "alert" : [6,17].includes(index) ? "unknown" : "healthy", duration: 420+offset*60, initialProgress: [0.2,0.46,0.68][offset], source: "display_scenario" });
    });
  }
  return trips;
}

export function tripProgress(trip: ShipmentTrip, elapsedSeconds: number): number {
  return Math.min(1, Math.max(0, trip.initialProgress + elapsedSeconds / trip.duration));
}
export const TRIP_STATUS = { alert: "شذوذ قوي · يحتاج فحصًا عند الوصول", healthy: "لا تنبيه في بيانات العرض", unknown: "المراقبة غير مكتملة" };
export const STATION_SVG = '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 28V12l13-8 13 8v16H3Z"/><path d="M3 12h26M12 7V4h8v3M8 28V17h5v11m6 0V17h5v11"/><path d="M8 21h5m6 0h5"/></svg>';
export const TRUCK_SVG = '<svg viewBox="0 0 32 26" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 3h18v16H2V3Zm18 5h6l4 6v5H20M25 8v6h5"/><path d="M6 6v9m5-9v9m5-9v9"/><circle cx="7" cy="20" r="3" fill="var(--vehicle-bg,#fff)"/><circle cx="25" cy="20" r="3" fill="var(--vehicle-bg,#fff)"/></svg>';
