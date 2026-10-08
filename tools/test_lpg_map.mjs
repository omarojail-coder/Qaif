import assert from "node:assert/strict";
import fs from "node:fs";
import { STATIONS, makeStores, makeTrips, ownerAt, tripProgress } from "../frontend/src/lpgMapData.ts";
import { inBoundary } from "../frontend/src/geoRoutes.ts";
import { flightPoint } from "../frontend/src/droneFlight.ts";

const boundary=JSON.parse(fs.readFileSync(new URL("../frontend/public/saudi-boundary.geojson",import.meta.url),"utf8")).geometry;
const areas=JSON.parse(fs.readFileSync(new URL("../frontend/public/gasco-service-areas.geojson",import.meta.url),"utf8"));
assert.equal(STATIONS.length,7);
assert.equal(new Set(STATIONS.map(s=>s.id)).size,7);
assert.deepEqual(new Set(areas.features.map(f=>f.properties.station_id)),new Set(STATIONS.map(s=>s.id)));
const stores=makeStores(boundary,areas),trips=makeTrips(stores,boundary);
assert.ok(stores.length>=180,"Retailers must be spread across multiple towns and all service zones");
assert.equal(new Set(stores.map(s=>s.id)).size,stores.length);
for(const station of STATIONS){
  assert.ok(inBoundary(station.position,boundary),station.name);
  assert.equal(ownerAt(station.position,areas),station.id,`Station must be inside its own service territory: ${station.name}`);
  assert.ok(stores.filter(s=>s.stationId===station.id).length>=14,station.name);
  assert.equal(trips.filter(t=>t.stationId===station.id).length,3,station.name);
  assert.equal(new Set(trips.filter(t=>t.stationId===station.id).map(t=>t.destination.city)).size,3,`Routes must show distinct destination towns: ${station.name}`);
}
for(const store of stores){
  assert.ok(inBoundary(store.position,boundary),store.id);
  assert.equal(ownerAt(store.position,areas),store.stationId,store.id);
}
assert.equal(trips.length,21);
assert.equal(trips.filter(t=>t.status==="alert").length,4);
assert.equal(trips.filter(t=>t.status==="unknown").length,2);
assert.equal(new Set(trips.map(t=>t.saddleId)).size,trips.length);
let positions=0;
for(const trip of trips){
  const station=STATIONS.find(s=>s.id===trip.stationId);
  assert.deepEqual(trip.path[0],station.position);
  assert.deepEqual(trip.path.at(-1),trip.destination.position);
  assert.equal(trip.source,"display_scenario");
  assert.equal(trip.destination.stationId,trip.stationId);
  for(let i=0;i<=500;i++){
    assert.ok(inBoundary(flightPoint(trip.path,i/500),boundary),`${trip.id} exits Saudi Arabia`);
    positions++;
  }
  assert.ok(tripProgress(trip,30)>tripProgress(trip,0));
  assert.equal(tripProgress(trip,1000000),1);
  assert.equal(tripProgress(trip,-1000000),0);
}
console.log(JSON.stringify({result:"PASS",stations:STATIONS.length,stores:stores.length,trips:trips.length,strong_alerts:4,unknown:2,inside_saudi_positions:positions}));
