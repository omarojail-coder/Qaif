import { STATIONS, makeStores, makeTrips, type ShipmentTrip } from './lpgMapData';

const prefix = 'qaif.lpg.trip.';
const lastSelectionKey = 'qaif.lpg.last-trip';
let catalog: Promise<ShipmentTrip[]> | null = null;
export const pageFromHash = () => {
  const page = location.hash.slice(1).split('?')[0] || 'map';
  return page === 'drone' ? 'cylinders' : page;
};

export function loadShipmentTrips(): Promise<ShipmentTrip[]> {
  if (!catalog) {
    const read = async (url: string) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error('تعذر تحميل قائمة أسرجة الشحنة.');
      return response.json();
    };
    catalog = Promise.all([read('/saudi-boundary.geojson'), read('/gasco-service-areas.geojson')])
      .then(([boundary, areas]) => {
        const trips = makeTrips(makeStores(boundary.geometry, areas), boundary.geometry);
        if (!trips.length) throw new Error('لا توجد رحلات شحنة متاحة.');
        return trips;
      }).catch(error => { catalog = null; throw error; });
  }
  return catalog;
}

export function saveShipmentSelection(trip: ShipmentTrip): ShipmentTrip {
  const value = { ...trip, viewProgress: trip.viewProgress ?? trip.initialProgress, viewStartedMs: trip.viewStartedMs ?? Date.now() };
  try {
    sessionStorage.setItem(prefix + value.id, JSON.stringify(value));
    sessionStorage.setItem(lastSelectionKey, value.id);
  } catch { /* Navigation still works if storage is unavailable. */ }
  return value;
}

export function readShipmentSelection(): ShipmentTrip | null {
  try {
    const id = new URLSearchParams(location.hash.split('?')[1]).get('trip') || sessionStorage.getItem(lastSelectionKey);
    if (!id || !/^TRIP-\d{3}$/.test(id)) return null;
    const value = JSON.parse(sessionStorage.getItem(prefix + id) || 'null');
    if (value?.id !== id || value.source !== 'display_scenario' || !STATIONS.some(s => s.id === value.stationId)
      || !Array.isArray(value.path) || value.path.length < 2 || !value.path.every((p: unknown) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))
      || !value.destination?.city || !Number.isFinite(value.duration) || value.duration <= 0
      || !Number.isFinite(value.viewProgress) || !Number.isFinite(value.viewStartedMs)) return null;
    return value;
  } catch { return null; }
}
