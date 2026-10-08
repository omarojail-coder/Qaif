export const SPACING_M = 31;
// Number of proposed locations at 0, 31, 62, ... within the declared length.
// A final partial interval never receives a fictitious endpoint sensor.
export function plannedCount(lengthKm?: number | null, historical = false) {
  return !historical &&
    typeof lengthKm === "number" &&
    Number.isFinite(lengthKm) &&
    lengthKm > 0 &&
    lengthKm <= 10000
    ? Math.floor((lengthKm * 1000) / SPACING_M) + 1
    : null;
}
export function planningWindow(count: number, page: number, windowSize = 20) {
  const pages = Math.max(1, Math.ceil(count / windowSize));
  const safePage = Math.min(Math.max(0, page), pages - 1);
  const start = safePage * windowSize;
  return {
    page: safePage,
    pages,
    points: Array.from(
      { length: Math.min(windowSize, count - start) },
      (_, i) => ({ index: start + i + 1, meters: (start + i) * SPACING_M }),
    ),
  };
}
