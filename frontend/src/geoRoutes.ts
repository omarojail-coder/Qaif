// Geographic display corridors, not surveyed pipeline alignment or dispatch GIS.
// Destinations are described in the linked operator sources; intermediate points
// are approximate. Land is clipped to the bundled Natural Earth Saudi polygon.
export type Position = [number, number];
export type Boundary = { type: string; coordinates: any };
export const ROUTES: Record<string, Position[]> = {
  "P-1": [
    [49.05, 24.1],
    [49.26, 25.19],
    [49.67, 25.92],
    [49.66, 27.0],
  ],
  "P-2": [
    [49.67, 25.92],
    [49.16, 25.65],
    [48.42, 25.23],
    [47.32, 24.94],
    [46.48, 24.78],
    [45.34, 24.52],
    [44.08, 24.35],
    [42.83, 24.22],
    [41.58, 24.29],
    [40.55, 24.14],
    [39.46, 24.09],
    [38.77, 24.18],
    [38.15, 24.02],
  ],
  "P-3": [
    [49.67, 25.92],
    [49.73, 26.12],
    [49.86, 26.38],
    [49.96, 26.55],
    [49.97, 26.75],
    [50.035, 26.75],
    [50.06, 26.725],
    [50.09207, 26.70243],
  ],
  "P-4": [
    [54.0, 22.52],
    [53.35, 22.55],
    [52.7, 22.85],
    [51.85, 23.27],
    [50.9, 23.7],
    [50.23, 24.38],
    [49.92, 25.12],
    [49.67, 25.92],
  ],
  "P-5": [
    [49.99, 26.56],
    [49.85, 26.33],
    [49.73, 26.11],
    [49.67, 25.92],
  ],
  "P-6": [
    [49.67, 25.92],
    [49.83, 25.98],
    [49.94, 26.05],
    [50.14, 26.05],
    [50.3, 26.04],
    [50.46, 26.05],
  ],
  "P-7": [
    [49.05, 24.1],
    [49.14, 24.39],
    [49.25, 24.73],
    [49.38, 25.13],
  ],
  "P-8": [
    [49.99, 26.56],
    [48.99, 27.1],
    [47.73, 27.65],
    [46.13, 28.31],
    [44.82, 28.96],
    [43.49, 29.63],
    [42.2, 30.27],
    [41.0, 30.98],
    [39.93, 31.36],
    [38.65, 31.68],
  ],
};
const cross = (a: Position, b: Position) => a[0] * b[1] - a[1] * b[0];
const sub = (a: Position, b: Position): Position => [a[0] - b[0], a[1] - b[1]];
const lerp = (a: Position, b: Position, t: number): Position => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
];
const near = (a: Position, b: Position) =>
  Math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-8;
export function polygons(g: Boundary): Position[][][] {
  return g.type === "Polygon"
    ? [g.coordinates]
    : g.type === "MultiPolygon"
      ? g.coordinates
      : [];
}
function inRing(p: Position, ring: Position[]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[j],
      b = ring[i],
      ap = sub(p, a),
      ab = sub(b, a);
    if (
      Math.abs(cross(ap, ab)) < 1e-9 &&
      p[0] >= Math.min(a[0], b[0]) - 1e-9 &&
      p[0] <= Math.max(a[0], b[0]) + 1e-9 &&
      p[1] >= Math.min(a[1], b[1]) - 1e-9 &&
      p[1] <= Math.max(a[1], b[1]) + 1e-9
    )
      return true;
    if (
      a[1] > p[1] !== b[1] > p[1] &&
      p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]
    )
      inside = !inside;
  }
  return inside;
}
export function inBoundary(p: Position, g: Boundary) {
  return polygons(g).some(
    (poly) =>
      inRing(p, poly[0]) && !poly.slice(1).some((hole) => inRing(p, hole)),
  );
}
// Split exactly at coastline/border crossings; retain connected parts separately.
export function clipRoute(
  line: Position[],
  g: Boundary,
  inside = true,
): Position[][] {
  const rings = polygons(g).flat(),
    parts: Position[][] = [];
  for (let i = 1; i < line.length; i++) {
    const a = line[i - 1],
      b = line[i],
      ab = sub(b, a),
      ts = [0, 1];
    for (const ring of rings)
      for (let j = 1; j < ring.length; j++) {
        const c = ring[j - 1],
          d = ring[j],
          cd = sub(d, c),
          den = cross(ab, cd);
        if (Math.abs(den) < 1e-12) continue;
        const ac = sub(c, a),
          t = cross(ac, cd) / den,
          u = cross(ac, ab) / den;
        if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push(t);
      }
    const sorted = [...new Set(ts)].sort((x, y) => x - y);
    for (let j = 1; j < sorted.length; j++) {
      const t0 = sorted[j - 1],
        t1 = sorted[j];
      if (t1 - t0 < 1e-10) continue;
      if (inBoundary(lerp(a, b, (t0 + t1) / 2), g) !== inside) continue;
      const from = lerp(a, b, t0),
        to = lerp(a, b, t1),
        last = parts.at(-1);
      if (last && near(last.at(-1)!, from)) last.push(to);
      else parts.push([from, to]);
    }
  }
  return parts;
}
export function routeFeatures(g: Boundary) {
  return Object.entries(ROUTES).flatMap(([id, line]) => {
    const features: any[] = [];
    const clipped = clipRoute(line, g);
    const land = id === "P-6" ? clipped.slice(0, 1) : clipped;
    if (land.length)
      features.push({
        type: "Feature",
        properties: { route_id: id, segment: "land" },
        geometry: { type: "MultiLineString", coordinates: land },
      });
    // AB-4 has an operator-documented offshore segment. No other out-of-country
    // geometry is silently classified as sea; Bahrain land is not drawn here.
    if (id === "P-6") {
      // Start at the first Saudi coastline crossing and continue offshore to
      // Bahrain's coast. Tiny shoreline/island re-entries are not new land legs.
      const seaParts = clipRoute(line, g, false);
      const start = seaParts[0]?.[0];
      const edge = start
        ? line.findIndex(
            (b, i) =>
              i > 0 &&
              Math.abs(cross(sub(start, line[i - 1]), sub(b, line[i - 1]))) <
                1e-8 &&
              start[0] >= Math.min(line[i - 1][0], b[0]) - 1e-9 &&
              start[0] <= Math.max(line[i - 1][0], b[0]) + 1e-9,
          )
        : -1;
      const sea = start && edge >= 1 ? [[start, ...line.slice(edge)]] : [];
      if (sea.length)
        features.push({
          type: "Feature",
          properties: { route_id: id, segment: "sea" },
          geometry: { type: "MultiLineString", coordinates: sea },
        });
    }
    return features;
  });
}
function km(a: Position, b: Position) {
  const rad = Math.PI / 180,
    dlat = (b[1] - a[1]) * rad,
    dlon = (b[0] - a[0]) * rad;
  return (
    6371 *
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin(dlat / 2) ** 2 +
          Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dlon / 2) ** 2,
      ),
    )
  );
}
// Display a normalized chainage on approximate geography, never an installation coordinate.
export function pointAlong(
  parts: Position[][],
  fraction: number,
): Position | null {
  const segments = parts.flatMap((part) =>
    part.slice(1).map((b, i) => ({ a: part[i], b, length: km(part[i], b) })),
  );
  const total = segments.reduce((s, p) => s + p.length, 0);
  if (!total) return null;
  let remaining = Math.max(0, Math.min(1, fraction)) * total;
  for (const p of segments) {
    if (remaining <= p.length) return lerp(p.a, p.b, remaining / p.length);
    remaining -= p.length;
  }
  return segments.at(-1)!.b;
}
