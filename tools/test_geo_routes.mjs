import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import {
  inBoundary,
  clipRoute,
  routeFeatures,
  pointAlong,
} from "../frontend/src/geoRoutes.ts";
import {
  displayPosition,
  DISPLAY_LOCATIONS,
} from "../frontend/src/mapLocations.ts";
const boundary = JSON.parse(
  fs.readFileSync(
    fileURLToPath(
      new URL("../frontend/public/saudi-boundary.geojson", import.meta.url),
    ),
    "utf8",
  ),
).geometry;
const features = routeFeatures(boundary);
let checks = 0;
for (const f of features.filter((f) => f.properties.segment === "land")) {
  assert.equal(
    f.geometry.coordinates.length,
    1,
    `${f.properties.route_id} must remain a continuous land corridor`,
  );
  for (const part of f.geometry.coordinates)
    for (let i = 1; i < part.length; i++)
      for (let j = 0; j <= 20; j++) {
        const a = part[i - 1],
          b = part[i],
          p = [
            a[0] + ((b[0] - a[0]) * j) / 20,
            a[1] + ((b[1] - a[1]) * j) / 20,
          ];
        assert.ok(
          inBoundary(p, boundary),
          `${f.properties.route_id} exits Saudi Arabia at ${p}`,
        );
        checks++;
      }
}
const sea = features.filter((f) => f.properties.segment === "sea");
assert.equal(sea.length, 1);
assert.equal(sea[0].properties.route_id, "P-6");
const ab4land = features.find(
  (f) => f.properties.route_id === "P-6" && f.properties.segment === "land",
);
assert.deepEqual(
  ab4land.geometry.coordinates[0].at(-1),
  sea[0].geometry.coordinates[0][0],
);
assert.ok(!inBoundary(sea[0].geometry.coordinates[0].at(-1), boundary));
for (const [id, p] of Object.entries(DISPLAY_LOCATIONS)) {
  assert.ok(inBoundary(p.after, boundary), id);
  assert.deepEqual(
    displayPosition({
      id,
      lon: p.before[0],
      lat: p.before[1],
      source: "simulation",
    }),
    p.after,
  );
  assert.deepEqual(
    displayPosition({
      id,
      lon: p.before[0],
      lat: p.before[1],
      source: "field",
    }),
    p.before,
    "field locations must never be moved by a display correction",
  );
  assert.deepEqual(
    displayPosition({
      id,
      lon: p.before[0] + 1,
      lat: p.before[1],
      source: "simulation",
    }),
    [p.before[0] + 1, p.before[1]],
    "edited coordinates must retain their values",
  );
}
const square = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [4, 0],
      [4, 4],
      [0, 4],
      [0, 0],
    ],
  ],
};
assert.deepEqual(
  clipRoute(
    [
      [-1, 2],
      [5, 2],
    ],
    square,
  ),
  [
    [
      [0, 2],
      [4, 2],
    ],
  ],
);
assert.deepEqual(
  clipRoute(
    [
      [-1, 2],
      [5, 2],
    ],
    square,
    false,
  ),
  [
    [
      [-1, 2],
      [0, 2],
    ],
    [
      [4, 2],
      [5, 2],
    ],
  ],
);
const withHole = {
  type: "Polygon",
  coordinates: [
    ...square.coordinates,
    [
      [1, 1],
      [3, 1],
      [3, 3],
      [1, 3],
      [1, 1],
    ],
  ],
};
assert.deepEqual(
  clipRoute(
    [
      [-1, 2],
      [5, 2],
    ],
    withHole,
  ),
  [
    [
      [0, 2],
      [1, 2],
    ],
    [
      [3, 2],
      [4, 2],
    ],
  ],
);
assert.deepEqual(
  pointAlong(
    [
      [
        [0, 0],
        [1, 0],
      ],
      [
        [3, 0],
        [4, 0],
      ],
    ],
    0.75,
  ),
  [3.5, 0],
);
console.log(
  `Geographic checks passed: ${checks} land samples, 8 continuous land routes, AB-4 sea continuity, clipping holes, and display-source preservation.`,
);
