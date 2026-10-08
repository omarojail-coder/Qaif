// Keep customer/PDF place labels identical to the existing display map.
import fs from 'node:fs';
import { STATIONS, makeStores, makeTrips } from '../frontend/src/lpgMapData.ts';

const boundary = JSON.parse(fs.readFileSync(new URL('../frontend/public/saudi-boundary.geojson', import.meta.url), 'utf8')).geometry;
const areas = JSON.parse(fs.readFileSync(new URL('../frontend/public/gasco-service-areas.geojson', import.meta.url), 'utf8'));
const places = makeTrips(makeStores(boundary, areas), boundary).map(trip => {
  const station = STATIONS.find(s => s.id === trip.stationId);
  return { number: Number(trip.id.slice(5)), initial_progress: trip.initialProgress,
    station: { name: `غازكو · ${station.name}`, city: station.name.replace('محطة ', ''), region: station.region, position: station.position },
    store: { name: trip.destination.name, city: trip.destination.city, region: station.region, position: trip.destination.position },
    path: trip.path, cities: station.cities };
});
if (places.length !== 21) throw new Error('Expected the 21 existing display routes');
fs.writeFileSync(new URL('../backend/assets/lpg-report-places.json', import.meta.url), JSON.stringify(places, null, 2) + '\n');
console.log(`Customer labels generated for ${places.length} existing routes.`);
