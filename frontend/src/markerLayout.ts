export type ScreenPoint = { x: number; y: number };
export type ScreenBox = ScreenPoint & { width: number; height: number };
export type FacilityGroup<T> = { records: T[]; anchor: ScreenPoint };

export function boxesOverlap(a: ScreenBox, b: ScreenBox, gap = 6) {
  return Math.abs(a.x - b.x) < (a.width + b.width) / 2 + gap &&
    Math.abs(a.y - b.y) < (a.height + b.height) / 2 + gap;
}

// Screen-space grouping keeps nearby cards together at every map scale.
// Saddles never enter this collection; their reserved boxes are placed first.
export function groupFacilities<T extends { id: string }>(
  points: { record: T; point: ScreenPoint }[],
  zoom: number,
): FacilityGroup<T>[] {
  const groups = [...points]
    .sort((a, b) => a.record.id.localeCompare(b.record.id))
    .map(({ record, point }) => ({ records: [record], anchor: point }));
  // Very close/coincident sites are spread into separate connected markers.
  if (zoom >= 11) return groups;
  const dimensions = (group: FacilityGroup<T>): ScreenBox => ({
    ...group.anchor,
    width: group.records.length > 1 ? 62 : 34,
    height: 38,
  });
  let merged = true;
  while (merged) {
    merged = false;
    for (let i = 0; i < groups.length && !merged; i++) {
      for (let j = i + 1; j < groups.length; j++) {
        if (!boxesOverlap(dimensions(groups[i]), dimensions(groups[j]), 10)) continue;
        const a = groups[i], b = groups[j];
        const count = a.records.length + b.records.length;
        a.anchor = {
          x: (a.anchor.x * a.records.length + b.anchor.x * b.records.length) / count,
          y: (a.anchor.y * a.records.length + b.anchor.y * b.records.length) / count,
        };
        a.records.push(...b.records);
        groups.splice(j, 1);
        merged = true;
        break;
      }
    }
  }
  return groups;
}

// Choose the closest available screen position without changing any coordinates.
export function placeMarker(
  anchor: ScreenPoint,
  width: number,
  height: number,
  occupied: ScreenBox[],
  bounds: { width: number; height: number },
): ScreenPoint {
  const inside = (p: ScreenPoint) => p.x >= width / 2 + 5 &&
    p.x <= bounds.width - width / 2 - 5 && p.y >= height / 2 + 5 &&
    p.y <= bounds.height - height / 2 - 5;
  const clear = (p: ScreenPoint) => inside(p) &&
    !occupied.some(box => boxesOverlap({ ...p, width, height }, box));
  const origin = {
    x: Math.max(width / 2 + 5, Math.min(bounds.width - width / 2 - 5, anchor.x)),
    y: Math.max(height / 2 + 5, Math.min(bounds.height - height / 2 - 5, anchor.y)),
  };
  let position: ScreenPoint | undefined;
  for (const radius of [0, 18, 36, 54, 72, 96, 128, 168]) {
    for (const [dx, dy] of [[0, -1], [-1, 0], [1, 0], [0, 1], [-0.707, -0.707], [0.707, -0.707], [-0.707, 0.707], [0.707, 0.707]]) {
      const candidate = { x: origin.x + dx * radius, y: origin.y + dy * radius };
      if (clear(candidate)) { position = candidate; break; }
    }
    if (position) break;
  }
  if (!position) {
    const candidates: ScreenPoint[] = [];
    for (let y = height / 2 + 5; y < bounds.height - height / 2; y += 16) {
      for (let x = width / 2 + 5; x < bounds.width - width / 2; x += 16) candidates.push({ x, y });
    }
    candidates.sort((a, b) => Math.hypot(a.x - origin.x, a.y - origin.y) - Math.hypot(b.x - origin.x, b.y - origin.y));
    position = candidates.find(clear) || origin;
  }
  occupied.push({ ...position, width, height });
  return position;
}
