import type { Position } from "./geoRoutes";
// Display corrections for the old illustrative seed only. An edited coordinate
// or a record from another source retains its own location. No DB record moves.
export const DISPLAY_LOCATIONS: Record<
  string,
  { before: Position; after: Position; source: string }
> = {
  "gas-3": {
    before: [49.7, 27],
    after: [49.07, 27.11],
    source:
      "https://ntrs.nasa.gov/api/citations/20250005862/downloads/1257656.pdf?attachment=true",
  },
  "gas-9": {
    before: [49.71, 27.28],
    after: [49.31, 27.11],
    source:
      "https://ntrs.nasa.gov/api/citations/20250005862/downloads/1257656.pdf?attachment=true",
  },
  "refinery-2": {
    before: [50.14, 26.65],
    after: [50.09207, 26.70243],
    source: "https://globalenergyobservatory.org/geoid/39104",
  },
  "refinery-5": {
    before: [39.16, 21.4],
    after: [39.18222, 21.45139],
    source:
      "https://www.itu.int/net/ITU-R/publications/brific-ter/files/ific/2003/ific2503.PDF",
  },
  "S-12": {
    before: [49.6523, 27.0321],
    after: [49.66, 27.0],
    source: "demonstration_saddle_at_asset",
  },
  "S-3": {
    before: [50.14, 26.65],
    after: [50.09207, 26.70243],
    source: "demonstration_saddle_at_asset",
  },
};
export function displayPosition(record: any): Position {
  const p: Position = [record.lon, record.lat],
    correction = DISPLAY_LOCATIONS[record.id];
  return correction &&
    ["illustrative_inventory", "simulation"].includes(record.source) &&
    Math.abs(p[0] - correction.before[0]) < 1e-6 &&
    Math.abs(p[1] - correction.before[1]) < 1e-6
    ? correction.after
    : p;
}
