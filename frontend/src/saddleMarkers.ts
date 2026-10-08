export type SaddleStatus = "alert" | "healthy" | "unknown";
export const SADDLE_DETAIL_ZOOM = 7.5;

// Acknowledging an alert does not resolve the condition that raised it.
export function hasSaddleAlert(id: string, alerts: any[]): boolean {
  return alerts.some(a => a.saddle_id === id && ["new", "acknowledged"].includes(a.status));
}

export function saddleStatus(saddle: any, alerts: any[]): SaddleStatus {
  if (hasSaddleAlert(saddle.id, alerts)) return "alert";
  if (!saddle.ai) return "unknown";
  if (saddle.ai) {
    const signals = Object.values(saddle.ai.signals || {}) as any[];
    if (signals.some(signal => signal.alarm === true)) return "alert";
    if (saddle.ai.status !== "active" || signals.length !== 4 || signals.some(signal => signal.state !== "absent")) return "unknown";
  }
  const row = saddle.latest;
  const channels = ["timestamp_s", "strain_hoop_microstrain", "strain_axial_microstrain", "temperature_k", "wetness_index"];
  if (saddle.quality !== "good" || row?.packet_valid !== true ||
      !channels.every(key => typeof row[key] === "number" && Number.isFinite(row[key]))) return "unknown";
  return "healthy";
}

export function saddleVisible(status: SaddleStatus, zoom: number): boolean {
  return status === "alert" || zoom >= SADDLE_DETAIL_ZOOM;
}

export const SADDLE_STATUS_LABELS: Record<SaddleStatus, string> = {
  alert: "تنبيه قائم",
  healthy: "قراءات سليمة",
  unknown: "بانتظار قراءات صالحة",
};

// A sensor patch wrapped around a pipe; shared by markers and the map key.
export const SADDLE_ICON_BODY = `<rect x="2" y="9" width="28" height="12" rx="5" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="11" y="3" width="10" height="24" rx="3" fill="currentColor"/><path d="M14 7h4M14 23h4" stroke="var(--saddle-color, #16805e)" stroke-width="1.5" stroke-linecap="round"/><circle cx="16" cy="15" r="2.3" fill="var(--saddle-color, #16805e)"/>`;
export function saddleIconSvg(): string {
  return `<svg viewBox="0 0 32 30" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">${SADDLE_ICON_BODY}</svg>`;
}
